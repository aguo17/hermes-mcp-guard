#!/usr/bin/env python3
"""
Hermes Guard — Unified Self-Evolution Engine

三層防禦，一次呼叫：
  Linter  → 執行前檢查 pitfalls.json，阻擋已知危險操作
  Interceptor → 執行後比對錯誤，自動匹配已知坑
  Memory → 必要時更新 skill pitfalls，防止下次再犯

用法:
  hermes_guard check <operation_type>     # Linter: 操作前檢查
  hermes_guard catch "<error_message>"    # Interceptor: 錯誤匹配
  hermes_guard fix <pitfall_id>           # 自動修復
  hermes_guard wrap "<command>"           # 全自動：檢查→執行→攔截→修復
  hermes_guard learn "<error>" "<fix>"    # 學到新坑，自動更新 pitfalls.json

這是 Agent 在執行任何 systemd/docker/pip/port/litellm 操作前「必須」呼叫的工具。
"""
import json, os, re, subprocess, sys, time
from pathlib import Path
from datetime import datetime

# 知識圖譜查表（可選 — 圖譜不存在時跳過）
try:
    from kg_lookup import lookup as kg_lookup
except ImportError:
    kg_lookup = None

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
PITFALLS_FILE = HERMES_HOME / "self_evolution" / "pitfalls.json"          # 生產：人工審核過的坑
STAGING_FILE = HERMES_HOME / "self_evolution" / "staging_pitfalls.json"  # 待審：Agent 提案的新坑
EVOLUTION_LOG = HERMES_HOME / "self_evolution" / "evolution.log"
SERVICE_REGISTRY = HERMES_HOME / "self_evolution" / "active_services.json"

CATEGORY_MAP = {
    "systemd": ["litellm", "system"],
    "docker": ["docker", "system"],
    "pip": ["litellm", "system"],
    "port": ["litellm", "docker", "system"],
    "api": ["api", "litellm"],
    "litellm": ["litellm", "api", "system"],
    "git": ["system"],
    "all": None
}

def log_event(event_type, detail):
    """Log evolution events."""
    EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EVOLUTION_LOG, "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {event_type}: {detail}\n")

def load_pitfalls():
    """載入生產環境 pitfalls（全自動模式無 staging）。"""
    if PITFALLS_FILE.exists():
        try:
            return json.loads(PITFALLS_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"pitfalls": []}

def run_check(cmd):
    """Run a shell guard check. Returns True if triggered (problem found)."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return bool(result.stdout.strip())
    except Exception:
        return False

# ═══════════════════════════════════════════
# LAYER 1: LINTER — Pre-execution check
# ═══════════════════════════════════════════

def linter_check(op_type):
    """Check all relevant pitfalls before executing an operation."""
    pitfalls = load_pitfalls()
    target_cats = CATEGORY_MAP.get(op_type)
    
    warnings = []
    blocks = []
    
    for pf in pitfalls.get("pitfalls", []):
        if target_cats is not None and pf["category"] not in target_cats:
            continue
        if not pf.get("guard_check"):
            continue
        
        triggered = run_check(pf["guard_check"])
        if triggered:
            entry = {
                "id": pf["id"],
                "severity": pf["severity"],
                "description": pf["description"],
                "auto_fix": pf.get("auto_fix"),
                "remediation": pf.get("remediation", [])
            }
            if pf["severity"] == "critical":
                blocks.append(entry)
            else:
                warnings.append(entry)
    
    safe = len(blocks) == 0
    result = {
        "layer": "linter",
        "safe": safe,
        "operation": op_type,
        "warnings": warnings,
        "blocks": blocks,
        "verdict": "PROCEED" if safe else "BLOCKED"
    }
    
    if not safe:
        log_event("LINTER_BLOCK", f"op={op_type} blocks={[b['id'] for b in blocks]}")
    
    return result

# ═══════════════════════════════════════════
# LAYER 2: INTERCEPTOR — Post-error matching
# ═══════════════════════════════════════════

def interceptor_catch(error_text):
    """Match error output against known pitfalls."""
    pitfalls = load_pitfalls()
    matches = []
    
    for pf in pitfalls.get("pitfalls", []):
        for pattern in pf.get("error_patterns", []):
            try:
                if re.search(pattern, error_text, re.IGNORECASE):
                    matches.append({
                        "id": pf["id"],
                        "description": pf["description"],
                        "severity": pf["severity"],
                        "source": pf.get("source", "manual"),
                        "matched_pattern": pattern,
                        "auto_fix": pf.get("auto_fix"),
                        "remediation": pf.get("remediation", []),
                        "source_skill": pf.get("source_skill")
                    })
                    break
            except re.error:
                continue
    
    result = {
        "layer": "interceptor",
        "matched": len(matches) > 0,
        "match_count": len(matches),
        "matches": matches
    }
    
    if matches:
        best = sorted(matches, key=lambda m: {"critical": 0, "high": 1, "medium": 2}.get(m["severity"], 3))[0]
        result["best_match"] = best
        log_event("INTERCEPTOR_MATCH", f"pattern={best['matched_pattern']} pitfall={best['id']}")
    
    return result

# ═══════════════════════════════════════════
# LAYER 3: AUTO-FIX
# ═══════════════════════════════════════════

def auto_fix_registry():
    return {
        "pin_litellm_150": _fix_pin_litellm,
        "set_dummy_openai_key": _fix_openai_key,
        "use_systemctl_restart": _fix_systemctl_restart,
        "remove_google_from_fallback": _fix_remove_google,
        "disk_cleanup": _fix_disk_cleanup,
    }

def _fix_pin_litellm():
    r = subprocess.run("python3.11 -m pip show litellm 2>/dev/null | grep Version", shell=True, capture_output=True, text=True)
    if "1.50" in r.stdout:
        return [{"status": "already_ok"}]
    subprocess.run("python3.11 -m pip install --user --break-system-packages 'litellm==1.50.0'", shell=True, timeout=60)
    return [{"status": "pinned_to_1.50"}]

def _fix_openai_key():
    svc = Path.home() / ".config/systemd/user/litellm-proxy.service"
    if svc.exists() and "OPENAI_API_KEY=dummy" not in svc.read_text():
        content = svc.read_text().replace("Environment=PYTHONUNBUFFERED=1", "Environment=PYTHONUNBUFFERED=1\nEnvironment=OPENAI_API_KEY=dummy")
        svc.write_text(content)
        subprocess.run("systemctl --user daemon-reload", shell=True)
        subprocess.run("systemctl --user restart litellm-proxy", shell=True, timeout=15)
        return [{"status": "fixed"}]
    return [{"status": "already_ok"}]

def _fix_systemctl_restart():
    subprocess.run("systemctl --user restart litellm-proxy", shell=True, timeout=15)
    return [{"status": "restarted"}]

def _fix_remove_google():
    config = HERMES_HOME / "litellm_config.yaml"
    content = config.read_text()
    if 'agent-free: ["agent-free-gh"]' in content:
        return [{"status": "already_ok"}]
    content = content.replace('- agent-free: ["agent-free-google"]\n    - agent-free-google: ["agent-free-gh"]', '- agent-free: ["agent-free-gh"]')
    config.write_text(content)
    subprocess.run("systemctl --user restart litellm-proxy", shell=True, timeout=15)
    return [{"status": "fixed"}]

def _fix_disk_cleanup():
    results = []
    r = subprocess.run("sudo du -sh /var/lib/docker/containers/*/*.log 2>/dev/null | sort -rh | head -5", shell=True, capture_output=True, text=True)
    for line in r.stdout.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) == 2 and ("G" in parts[0] or ("M" in parts[0] and float(parts[0][:-1]) > 500)):
            subprocess.run(f"sudo truncate -s 0 {parts[1]}", shell=True, timeout=10)
            results.append({"truncated": parts[1]})
    return results if results else [{"status": "nothing_to_clean"}]

def remediate(pitfall_id):
    pitfalls = load_pitfalls()
    target = next((p for p in pitfalls["pitfalls"] if p["id"] == pitfall_id), None)
    if not target:
        return {"success": False, "error": f"Pitfall not found: {pitfall_id}"}
    
    auto_fix = target.get("auto_fix")
    registry = auto_fix_registry()
    if auto_fix not in registry:
        return {"success": False, "reason": "no_auto_fix", "manual": target.get("remediation", [])}
    
    try:
        actions = registry[auto_fix]()
        log_event("AUTO_FIX", f"pitfall={pitfall_id} fix={auto_fix}")
        return {"success": True, "pitfall_id": pitfall_id, "actions": actions}
    except Exception as e:
        return {"success": False, "error": str(e), "manual": target.get("remediation", [])}

# ═══════════════════════════════════════════
# UNIFIED: WRAP — Linter → Execute → Interceptor → Fix
# ═══════════════════════════════════════════

def wrap_command(op_type, command):
    """Full pipeline: check → execute → catch errors → fix if possible."""
    result = {
        "command": command,
        "operation_type": op_type,
        "stages": {}
    }
    
    # Stage 1: Linter
    linter = linter_check(op_type)
    result["stages"]["linter"] = linter
    if not linter["safe"]:
        result["executed"] = False
        result["verdict"] = "BLOCKED_BY_LINTER"
        # Try auto-fix critical blocks
        for block in linter.get("blocks", []):
            if block.get("auto_fix"):
                fix_result = remediate(block["id"])
                result["stages"][f"auto_fix_{block['id']}"] = fix_result
                if fix_result.get("success"):
                    # Re-check after fix
                    linter = linter_check(op_type)
                    result["stages"]["linter_retry"] = linter
                    if linter["safe"]:
                        break
        if not linter["safe"]:
            return result
    
    # Stage 1.5: Knowledge Graph Pre-flight (經驗法則，僅警告不阻擋)
    kg_warnings = []
    if kg_lookup:
        try:
            kg_warnings = kg_lookup(command)
        except Exception:
            pass  # 圖譜查表不應阻止執行
    if kg_warnings:
        result["stages"]["kg_preflight"] = {
            "layer": "knowledge_graph",
            "warnings": kg_warnings,
            "verdict": "WARN"  # 僅警告，不阻擋
        }
    
    # Stage 2: Execute
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
        result["executed"] = True
        result["exit_code"] = r.returncode
        result["stdout_tail"] = r.stdout[-500:] if r.stdout else ""
        result["stderr_tail"] = r.stderr[-500:] if r.stderr else ""
        
        if r.returncode != 0:
            # Stage 3: Interceptor
            error_text = r.stderr + r.stdout
            interceptor = interceptor_catch(error_text)
            result["stages"]["interceptor"] = interceptor
            
            if interceptor["matched"]:
                # Stage 4: Auto-fix
                best = interceptor["best_match"]
                if best.get("auto_fix"):
                    fix_result = remediate(best["id"])
                    result["stages"]["auto_fix"] = fix_result
                    result["verdict"] = "FIXED" if fix_result.get("success") else "MATCHED_NO_FIX"
                else:
                    result["verdict"] = "MATCHED_NO_AUTO_FIX"
            else:
                result["verdict"] = "UNKNOWN_ERROR"
        else:
            result["verdict"] = "OK"
    except subprocess.TimeoutExpired:
        result["executed"] = False
        result["verdict"] = "TIMEOUT"
    except Exception as e:
        result["executed"] = False
        result["verdict"] = "EXCEPTION"
        result["exception"] = str(e)
    
    log_event("WRAP", f"cmd={command[:80]} verdict={result['verdict']}")
    return result

# ═══════════════════════════════════════════
# LEARN: 全自動進化 — 直接寫入生產環境
# ═══════════════════════════════════════════

# 禁止註冊的泛化關鍵字（會導致全域誤攔截）
FORBIDDEN_PATTERNS = ["error", "failed", "exception", "not found", "timeout", "traceback", ".*"]

def register_new_pitfall(error_segment: str, explanation: str, remediation_steps: str, category: str = "general", severity: str = "medium"):
    """
    全自動進化模式：驗證 Agent 提案，安全則直接寫入生產環境 pitfalls.json。
    
    安全網：
    1. 長度 ≥ 15 字元
    2. 禁止泛化關鍵字
    3. 自動標記 source=auto
    """
    # [安全網 1] 長度檢查
    if len(error_segment) < 15:
        return {"status": "rejected", "message": "❌ 註冊失敗：error_segment 太短（需 ≥15 字元），容易造成誤判。請擷取具體的 Stack Trace 片段。"}
    
    # [安全網 1] 泛化檢查
    if error_segment.strip().lower() in FORBIDDEN_PATTERNS:
        return {"status": "rejected", "message": f"❌ 註冊失敗：'{error_segment}' 太過泛化，會導致全域癱瘓。請提供具體錯誤訊息。"}
    
    import uuid
    # 🦅 遮罩邏輯：先保護 .* 萬用字元，再對其餘字串做 re.escape()
    # 防止 re.escape() 將刻意保留的 regex 萬用字元 .* 錯誤轉義為 \.\*
    # 案例：Journal file.*corrupted → 應保留 .* 的萬用能力，不應變成 \.\*
    WILDCARD_PLACEHOLDER = "___HERMES_WILDCARD___"
    masked = error_segment.replace(".*", WILDCARD_PLACEHOLDER)
    safe_pattern = re.escape(masked).replace(WILDCARD_PLACEHOLDER, ".*")
    
    # 讀取現有 prod
    prod_data = {"schema_version": "1.0", "pitfalls": []}
    if PITFALLS_FILE.exists():
        try:
            prod_data = json.loads(PITFALLS_FILE.read_text())
        except json.JSONDecodeError:
            pass
    
    # 去重
    existing_patterns = []
    for p in prod_data.get("pitfalls", []):
        existing_patterns.extend(p.get("error_patterns", []))
        mc = p.get("match_criteria", {})
        if mc.get("error_pattern"):
            existing_patterns.append(mc["error_pattern"])
    
    if safe_pattern in existing_patterns:
        return {"status": "skipped", "message": "此錯誤特徵已在防禦網中，無須重複註冊。"}
    
    # 建立新規則
    new_id = f"PF-AUTO-{uuid.uuid4().hex[:6].upper()}"
    new_entry = {
        "id": new_id,
        "source": "auto",  # [安全網 2] 標記為自動生成
        "created_at": datetime.now().isoformat(),
        "category": category,
        "severity": severity,
        "status": "active",
        "description": explanation,
        "error_patterns": [safe_pattern],
        "match_criteria": {
            "type": "regex",
            "error_pattern": safe_pattern,
            "original_segment": error_segment
        },
        "remediation": remediation_steps if isinstance(remediation_steps, list) else [remediation_steps],
        "auto_fix": None,
        "source_skill": "auto-learned"
    }
    
    # 直接寫入 prod
    prod_data["pitfalls"].append(new_entry)
    prod_data["updated"] = datetime.now().isoformat()
    PITFALLS_FILE.write_text(json.dumps(prod_data, indent=2, ensure_ascii=False))
    
    log_event("AUTO_LEARN", f"id={new_id} desc={explanation[:80]}")
    
    return {
        "status": "active",
        "id": new_id,
        "message": f"⚡ 全自動進化成功！規則 {new_id} 已即時生效並部署至攔截網。\n🧠 記住了：{explanation}"
    }

def revoke_pitfall(pitfall_id: str):
    """
    [後悔藥] 從生產環境中刪除一條自動生成的規則。
    僅能刪除 source=auto 的規則，手動規則受保護。
    """
    if not PITFALLS_FILE.exists():
        return {"status": "error", "message": "找不到 pitfalls.json"}
    
    try:
        prod_data = json.loads(PITFALLS_FILE.read_text())
    except json.JSONDecodeError:
        return {"status": "error", "message": "pitfalls.json 格式損壞"}
    
    target = None
    target_index = -1
    for i, p in enumerate(prod_data.get("pitfalls", [])):
        if p.get("id") == pitfall_id:
            target = p
            target_index = i
            break
    
    if target is None:
        return {"status": "error", "message": f"找不到 ID 為 {pitfall_id} 的規則"}
    
    # 保護手動規則
    if target.get("source") == "manual":
        return {"status": "protected", "message": f"⛔ {pitfall_id} 是手動建立的規則，受保護無法自動刪除。請手動編輯 pitfalls.json。"}
    
    prod_data["pitfalls"].pop(target_index)
    PITFALLS_FILE.write_text(json.dumps(prod_data, indent=2, ensure_ascii=False))
    
    log_event("REVOKE", f"id={pitfall_id} desc={target.get('description','')[:80]}")
    
    return {
        "status": "revoked",
        "id": pitfall_id,
        "message": f"🗑️ 已撤銷自動規則 {pitfall_id}。防禦網已更新。"
    }

# ═══════════════════════════════════════════
# TOOLS: 高階系統管理工具（Fail-Fast 設計）
# ═══════════════════════════════════════════

def inspect_system_state(category: str = "all") -> str:
    """
    系統狀態觀測器。獲取 CPU/RAM/VRAM/Disk 即時狀態。
    原生 Linux 實作（無外部依賴），在執行高負載操作前必須呼叫。
    """
    import platform
    
    state = {}
    
    if category in ["all", "hardware_info"]:
        state["os"] = f"{platform.system()} {platform.release()}"
        state["cpu_count"] = os.cpu_count()
        try:
            load = os.getloadavg()
            state["load_avg"] = {"1min": round(load[0], 2), "5min": round(load[1], 2), "15min": round(load[2], 2)}
        except Exception:
            state["load_avg"] = "unavailable"
    
    if category in ["all", "memory"]:
        # 從 /proc/meminfo 解析 (Linux 原生，無需 psutil)
        try:
            meminfo = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = int(parts[1].strip().split()[0])
                        meminfo[key] = val
            
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0) + meminfo.get("Buffers", 0) + meminfo.get("Cached", 0))
            used_kb = total_kb - meminfo.get("MemFree", 0) - meminfo.get("Buffers", 0) - meminfo.get("Cached", 0)
            
            state["ram"] = {
                "total_gb": round(total_kb / 1024**2, 2),
                "available_gb": round(avail_kb / 1024**2, 2),
                "used_gb": round(used_kb / 1024**2, 2),
                "usage_pct": round((1 - avail_kb / total_kb) * 100, 1) if total_kb > 0 else 0
            }
            
            swap_total = meminfo.get("SwapTotal", 0)
            swap_free = meminfo.get("SwapFree", 0)
            if swap_total > 0:
                state["swap"] = {
                    "total_gb": round(swap_total / 1024**2, 2),
                    "used_gb": round((swap_total - swap_free) / 1024**2, 2),
                    "usage_pct": round((1 - swap_free / swap_total) * 100, 1)
                }
        except Exception:
            state["ram"] = "unavailable"
        
        # VRAM: NVIDIA GPU
        if platform.system() == "Linux":
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", "--format=csv,nounits,noheader"],
                    capture_output=True, text=True, timeout=5
                )
                if res.returncode == 0 and res.stdout.strip():
                    parts = res.stdout.strip().split(",")
                    state["gpu_vram"] = {
                        "total_mb": int(parts[0].strip()),
                        "used_mb": int(parts[1].strip()),
                        "free_mb": int(parts[2].strip())
                    }
                else:
                    state["gpu_vram"] = "no NVIDIA GPU or driver missing"
            except Exception:
                state["gpu_vram"] = "nvidia-smi unavailable"
        
        elif platform.system() == "Darwin":
            state["gpu_vram"] = "Unified Memory (Apple Silicon) — see ram"
    
    if category in ["all", "storage"]:
        try:
            res = subprocess.run(["df", "-B1", "/"], capture_output=True, text=True, timeout=5)
            lines = res.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split()
                total = int(parts[1])
                used = int(parts[2])
                free = int(parts[3])
                state["disk"] = {
                    "total_gb": round(total / 1024**3, 2),
                    "free_gb": round(free / 1024**3, 2),
                    "used_gb": round(used / 1024**3, 2),
                    "usage_pct": round(used / total * 100, 1) if total > 0 else 0
                }
        except Exception:
            state["disk"] = "unavailable"
    
    return json.dumps(state, indent=2, ensure_ascii=False)

def list_active_services() -> str:
    """
    服務註冊表查詢工具（黑板機制）。
    讀取 active_services.json，回傳所有已註冊的背景服務狀態。
    每筆記錄包含：alias、PID、command、workspace、log_file、啟動時間、狀態。
    """
    if not SERVICE_REGISTRY.exists():
        return json.dumps({"services": [], "message": "尚無已註冊的背景服務"}, indent=2, ensure_ascii=False)

    try:
        registry = json.loads(SERVICE_REGISTRY.read_text())
    except json.JSONDecodeError:
        return json.dumps({"services": [], "error": "服務註冊表損壞"}, indent=2, ensure_ascii=False)

    services = registry.get("services", [])

    # 即時檢查每個服務的存活狀態
    for svc in services:
        pid = svc.get("pid")
        if pid and HAS_PSUTIL:
            try:
                proc = psutil.Process(pid)
                svc["status"] = "🟢 running"
                svc["alive"] = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                svc["status"] = "🔴 dead"
                svc["alive"] = False
        else:
            svc["status"] = "❓ unknown (psutil unavailable)"
            svc["alive"] = None

    return json.dumps({
        "total": len(services),
        "alive": sum(1 for s in services if s.get("alive")),
        "services": services
    }, indent=2, ensure_ascii=False)


def _register_service(alias: str, pid: int, command: str, workspace: str, log_file: str):
    """內部函數：寫入服務註冊表（黑板機制）"""
    registry = {"updated": datetime.now().isoformat(), "services": []}
    if SERVICE_REGISTRY.exists():
        try:
            registry = json.loads(SERVICE_REGISTRY.read_text())
        except json.JSONDecodeError:
            pass

    # 移除同 alias 的舊記錄
    registry["services"] = [s for s in registry.get("services", []) if s.get("alias") != alias]

    registry["services"].append({
        "alias": alias,
        "pid": pid,
        "command": command,
        "workspace": workspace,
        "log_file": log_file,
        "started_at": datetime.now().isoformat(),
    })
    registry["updated"] = datetime.now().isoformat()
    SERVICE_REGISTRY.write_text(json.dumps(registry, indent=2, ensure_ascii=False))

def spawn_background_process(command: str, workspace_dir: str, log_file_name: str = "background_service.log", wait_seconds: float = 2.0, service_alias: str = None):
    """
    非同步啟動常駐背景服務。Fire-and-Forget + 啟動健康檢查。
    Port 衝突、依賴缺失等錯誤會以 RuntimeError 拋出，供 Guard 攔截學習。
    """
    if not os.path.exists(workspace_dir):
        raise FileNotFoundError(f"[Errno 2] 工作目錄不存在: {workspace_dir}")
    
    args = command.split() if not isinstance(command, list) else command
    log_path = os.path.join(workspace_dir, log_file_name)
    
    kwargs = {}
    if os.name == 'posix':
        kwargs['start_new_session'] = True
    
    try:
        out_file = open(log_path, "w", encoding="utf-8")
        
        process = subprocess.Popen(
            args,
            cwd=workspace_dir,
            stdout=out_file,
            stderr=subprocess.STDOUT,
            **kwargs
        )
        
        time.sleep(wait_seconds)
        exit_code = process.poll()
        out_file.flush()
        
        with open(log_path, "r", encoding="utf-8") as f:
            initial_logs = f.read()[:1500]
        
        if exit_code is not None and exit_code != 0:
            raise RuntimeError(
                f"服務啟動失敗 (Exit Code {exit_code})！通常是 Port 被佔用或依賴缺失。\n"
                f"錯誤日誌片段:\n{initial_logs}"
            )
        
        result = {
            "status": "running_in_background",
            "pid": process.pid,
            "log_file": log_path,
            "initial_logs_preview": initial_logs if initial_logs else "無輸出或尚未產生日誌。"
        }

        # 寫入服務註冊表（黑板機制）
        alias = service_alias or f"bg-{process.pid}"
        _register_service(alias, process.pid, command, workspace_dir, log_path)
        result["service_alias"] = alias
        result["note"] = f"已註冊至黑板，可用 list_active_services 查詢"

        return json.dumps(result, indent=2, ensure_ascii=False)
    
    except Exception as e:
        if isinstance(e, (FileNotFoundError, RuntimeError)):
            raise
        raise RuntimeError(f"無法建立背景服務程序: {str(e)}")

def _remove_service_by_pid(pid: int):
    """內部函數：從註冊表中移除指定 PID 的服務記錄"""
    if not SERVICE_REGISTRY.exists():
        return
    try:
        registry = json.loads(SERVICE_REGISTRY.read_text())
    except json.JSONDecodeError:
        return
    before = len(registry.get("services", []))
    registry["services"] = [s for s in registry.get("services", []) if s.get("pid") != pid]
    if len(registry["services"]) < before:
        registry["updated"] = datetime.now().isoformat()
        SERVICE_REGISTRY.write_text(json.dumps(registry, indent=2, ensure_ascii=False))

def kill_process(pid: int, force: bool = False) -> str:
    """
    安全且精準地終止指定的背景程序（PID）。

    三層防禦：
      1. 系統核心保護 — PID ≤ 10 或 PID 1 (init/systemd) 絕對拒絕
      2. 防自殺機制 — 拒絕終止 Agent 自身主程序
      3. 驗明正身 — 用 psutil 確認 PID 存在，再執行處決

    Args:
        pid: 目標程序 ID
        force: False=SIGTERM（優雅終止），True=SIGKILL（強制獵殺）

    Returns:
        成功訊息字串，失敗拋出標準 Exception 供 Guard 攔截學習
    """
    if not HAS_PSUTIL:
        raise RuntimeError("缺少 psutil 依賴。請執行: pip install psutil")

    # ═══════════════════════════════════════
    # 🛡️ 絕對防禦機制 (Hard Limits)
    # ═══════════════════════════════════════

    # 1. 系統核心防護
    if pid <= 10:
        raise PermissionError(
            f"[安全攔截] 拒絕執行！PID {pid} 屬於作業系統核心保留程序，嚴禁獵殺。"
        )

    # 2. 防自殺機制
    if pid == os.getpid():
        raise ValueError(
            f"[安全攔截] 拒絕執行！PID {pid} 是 Agent 自身的主程序。你不能終止你自己。"
        )

    # ═══════════════════════════════════════
    # 🔍 驗明正身 (Process Verification)
    # ═══════════════════════════════════════
    try:
        target = psutil.Process(pid)
        process_name = target.name()
        cmdline = " ".join(target.cmdline()) if target.cmdline() else "(kernel/unknown)"
    except psutil.NoSuchProcess:
        # 程序已死，但可能還在註冊表中 → 清理殘留記錄
        _remove_service_by_pid(pid)
        raise ValueError(
            f"獵殺失敗：找不到 PID 為 {pid} 的程序。"
            "它可能已經關閉或崩潰。\n"
            "🧹 已自動清理服務註冊表中的殘留記錄。"
        )
    except psutil.AccessDenied:
        raise PermissionError(
            f"[Errno 13] 權限不足：無法讀取 PID {pid} 的資訊。這通常代表它是 root/管理員程序。"
        )

    # ═══════════════════════════════════════
    # ⚔️ 執行處決 (Execution)
    # ═══════════════════════════════════════
    try:
        if force:
            target.kill()  # SIGKILL
            action_type = "強制獵殺 (SIGKILL)"
        else:
            target.terminate()  # SIGTERM
            action_type = "優雅終止 (SIGTERM)"

        # 守屍：等待最多 3 秒確認程序真的斷氣
        target.wait(timeout=3)

        # 自動清理服務註冊表
        _remove_service_by_pid(pid)

        return (
            f"✅ 成功{action_type}程序 '{process_name}' (PID: {pid})。\n"
            f"   指令列: {cmdline[:80]}\n"
            f"   🧹 已自動從服務註冊表移除。"
        )

    except psutil.TimeoutExpired:
        raise RuntimeError(
            f"程序 '{process_name}' (PID: {pid}) 拒絕回應優雅終止訊號。\n"
            "修復建議：請將參數 `force` 設為 true 再次呼叫此工具進行強制獵殺。"
        )
    except psutil.AccessDenied:
        raise PermissionError(
            f"[Errno 13] 權限不足：無法終止程序 '{process_name}' (PID: {pid})，可能需要 sudo 提權。"
        )

def smart_tree_view(directory_path: str, max_depth: int = 2, filter_extension: str = None):
    """
    安全目錄探索器。支援深度限制與副檔名過濾，防止 token 爆炸。
    所有錯誤以標準 Exception 拋出，供 Guard 攔截學習。
    """
    if not os.path.exists(directory_path):
        raise FileNotFoundError(f"[Errno 2] 目錄不存在: {directory_path}")
    if not os.path.isdir(directory_path):
        raise NotADirectoryError(f"[Errno 20] 路徑不是一個目錄: {directory_path}")
    
    tree_str = f"📁 {directory_path}\n"
    base_depth = directory_path.rstrip(os.sep).count(os.sep)
    
    try:
        for root, dirs, files in os.walk(directory_path):
            current_depth = root.count(os.sep) - base_depth
            if current_depth >= max_depth:
                del dirs[:]
            
            indent = "  " * current_depth
            if current_depth > 0:
                tree_str += f"{indent}├─ 📁 {os.path.basename(root)}/\n"
            
            sub_indent = "  " * (current_depth + 1)
            for f in sorted(files):
                if filter_extension and not f.endswith(filter_extension):
                    continue
                tree_str += f"{sub_indent}├─ 📄 {f}\n"
    except PermissionError as e:
        raise PermissionError(f"[Errno 13] 權限不足，無法讀取部分目錄: {e}")
    
    output = tree_str.strip()
    if len(output) > 2000:
        return output[:2000] + "\n... (輸出過長已截斷，請縮小 max_depth 或使用 filter_extension)"
    return output

def patch_file_content(file_path: str, search_pattern: str, replacement_text: str, is_regex: bool = True):
    """
    外科手術檔案修改器。精準替換，不覆寫無關部分。
    所有錯誤以標準 Exception 拋出，供 Guard 攔截學習。
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"[Errno 2] 檔案不存在: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except PermissionError:
        raise PermissionError(f"[Errno 13] 權限不足，無法讀取: {file_path}")
    except UnicodeDecodeError:
        raise ValueError(f"無法解析檔案編碼，這可能是一個二進制檔: {file_path}")
    
    if is_regex:
        try:
            new_content, count = re.subn(search_pattern, replacement_text, content, flags=re.MULTILINE)
        except re.error as e:
            raise ValueError(f"正規表達式語法錯誤: {e}")
    else:
        count = content.count(search_pattern)
        new_content = content.replace(search_pattern, replacement_text)
    
    if count == 0:
        raise ValueError(f"修改失敗：在檔案中找不到特徵 '{search_pattern}'。請呼叫讀取工具確認檔案最新內容。")
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    except PermissionError:
        raise PermissionError(f"[Errno 13] 權限不足，無法寫入檔案 (可能需要提權): {file_path}")
    
    return f"✅ 成功修改檔案 {file_path}。共執行了 {count} 處替換。"

# ═══════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "error": "Usage:",
            "commands": {
                "check <op_type>": "Linter: pre-execution safety check",
                "catch <error>": "Interceptor: match error to known pitfalls",
                "fix <pitfall_id>": "Auto-remediate a known pitfall",
                "wrap <op_type> <cmd>": "Full: check → execute → catch → fix",
                "register <err> <desc> <fix> [cat]": "Learn: auto-register pitfall (validates then deploys)",
                "revoke <id>": "Undo: remove an auto-generated rule",
                "tree <path> [depth] [ext]": "Safe directory explorer with depth limit",
                "spatch <file> <search> <replace> [regex|text]": "Surgical file patcher",
                "inspect [memory|storage|hardware|all]": "System state inspector (RAM/VRAM/Disk/CPU)",
                "spawn <cmd> <dir> [wait_sec] [alias]": "Fire-and-forget background service launcher",
                "kill <pid> [force]": "Safe process terminator (anti-suicide + core protection)",
                "services": "List all registered background services (blackboard)",
                "list": "List all pitfalls with source (auto/manual)"
            }
        }, indent=2, ensure_ascii=False))
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "check":
        result = linter_check(sys.argv[2] if len(sys.argv) > 2 else "all")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["safe"] else 1)
    
    elif cmd == "catch":
        error_text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else sys.stdin.read()
        result = interceptor_catch(error_text)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["matched"] else 1)
    
    elif cmd == "fix":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: hermes_guard fix <pitfall_id>"}))
            sys.exit(1)
        result = remediate(sys.argv[2])
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result.get("success") else 1)
    
    elif cmd == "wrap":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: hermes_guard wrap <op_type> <command>"}))
            sys.exit(1)
        result = wrap_command(sys.argv[2], " ".join(sys.argv[3:]))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["verdict"] in ("OK", "FIXED") else 1)
    
    elif cmd == "register":
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: hermes_guard register <error_segment> <explanation> <remediation> [category] [severity]"}))
            sys.exit(1)
        result = register_new_pitfall(
            sys.argv[2], sys.argv[3], sys.argv[4],
            sys.argv[5] if len(sys.argv) > 5 else "general",
            sys.argv[6] if len(sys.argv) > 6 else "medium"
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif cmd == "revoke":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: hermes_guard revoke <pitfall_id>"}))
            sys.exit(1)
        result = revoke_pitfall(sys.argv[2])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    
    elif cmd == "tree":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: hermes_guard tree <directory> [max_depth] [filter_extension]"}))
            sys.exit(1)
        try:
            result = smart_tree_view(
                sys.argv[2],
                int(sys.argv[3]) if len(sys.argv) > 3 else 2,
                sys.argv[4] if len(sys.argv) > 4 else None
            )
            print(result)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    
    elif cmd == "spatch":
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: hermes_guard spatch <file> <search> <replace> [regex|text]"}))
            sys.exit(1)
        try:
            is_regex = sys.argv[5].lower() != "text" if len(sys.argv) > 5 else True
            result = patch_file_content(sys.argv[2], sys.argv[3], sys.argv[4], is_regex)
            print(result)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    
    elif cmd == "inspect":
        category = sys.argv[2] if len(sys.argv) > 2 else "all"
        try:
            result = inspect_system_state(category)
            print(result)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    
    elif cmd == "spawn":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: hermes_guard spawn <command> <workspace_dir> [wait_seconds] [service_alias]"}))
            sys.exit(1)
        try:
            result = spawn_background_process(
                sys.argv[2], sys.argv[3],
                wait_seconds=float(sys.argv[4]) if len(sys.argv) > 4 else 2.0,
                service_alias=sys.argv[5] if len(sys.argv) > 5 else None
            )
            print(result)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "services":
        try:
            result = list_active_services()
            print(result)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "kill":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "Usage: hermes_guard kill <pid> [force: true|false]"}))
            sys.exit(1)
        try:
            pid = int(sys.argv[2])
            force = sys.argv[3].lower() in ("true", "1", "force") if len(sys.argv) > 3 else False
            result = kill_process(pid, force=force)
            print(result)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    
    elif cmd == "list":
        pitfalls = load_pitfalls()
        summary = [{
            "id": p["id"], "severity": p["severity"], "source": p.get("source", "manual"),
            "description": p["description"], "auto_fix": bool(p.get("auto_fix")), "category": p["category"]
        } for p in pitfalls["pitfalls"]]
        auto_count = len([p for p in pitfalls["pitfalls"] if p.get("source") == "auto"])
        manual_count = len(summary) - auto_count
        print(json.dumps({"total": len(summary), "auto": auto_count, "manual": manual_count, "pitfalls": summary}, indent=2, ensure_ascii=False))
    
    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)

if __name__ == "__main__":
    main()
