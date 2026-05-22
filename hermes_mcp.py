#!/usr/bin/env python3
"""
Hermes MCP Guard Server
Author: aguo17
License: MIT
Description: A Zero-Latency, Self-Healing System Guard Server for AI Agents
using Anthropic's Model Context Protocol (MCP).
"""

import os
import sys
import json
import signal          # FIX #3: 移到頂層 import，避免清理中途失敗
import threading       # FIX #4: Rate limiter thread-safety
import subprocess
import time

from mcp.server.fastmcp import FastMCP

# ═══════════════════════════════════════════════════════
# Rate Limiting：防止 Agent 邏輯出錯導致的無限迴圈呼叫
# 🛡️ L-1 fix: 改用檔案鎖 — 跨行程生效，不再每次 MCP 呼叫重置
# ═══════════════════════════════════════════════════════

_MIN_INTERVAL = 0.5   # 每 0.5 秒最多執行一次防禦操作


def _get_cooldown_file() -> str:
    """延遲解析 cooldown 檔案路徑，避免 NameError（HERMES_HOME 定義順序問題）"""
    hermes_home = os.path.expanduser(os.environ.get("HERMES_HOME", os.path.join(os.path.expanduser("~"), ".hermes")))
    return os.path.join(hermes_home, "self_evolution", ".rate_limit")


def _check_cooldown() -> None:
    """冷卻檢查：使用 fcntl.flock() 做真正的跨行程原子鎖，防止 race condition"""
    import fcntl
    
    cooldown_file = _get_cooldown_file()
    os.makedirs(os.path.dirname(cooldown_file), exist_ok=True)
    now = time.time()
    
    try:
        with open(cooldown_file, "a+") as f:
            # 🛡️ P0: 真正的 advisory lock（跨行程原子操作）
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                content = f.read().strip()
                last_call = float(content) if content else 0.0
                
                elapsed = now - last_call
                if elapsed < _MIN_INTERVAL:
                    raise RuntimeError(
                        f"⏱️ 呼叫過於頻繁（距上次僅 {elapsed:.2f}s）。"
                        f"請等待 {_MIN_INTERVAL - elapsed:.2f}s 後再試。"
                    )
                
                # 原子寫入（仍持有鎖）
                f.seek(0)
                f.truncate()
                f.write(str(now))
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except RuntimeError:
        raise  # 重新拋出冷卻錯誤
    except Exception:
        pass  # 鎖機制失敗不應阻擋操作（graceful degradation）


# ═══════════════════════════════════════════════════════
# 啟動自檢
# ═══════════════════════════════════════════════════════

# 1. Root 權限警告
if hasattr(os, "geteuid") and os.geteuid() == 0:
    print(
        "⚠️ 警告：不建議以 root 權限執行 Hermes MCP Guard。"
        "請使用一般用戶身份。",
        file=sys.stderr,
    )

# 2. 動態定位路徑
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GUARD_SH = os.path.join(BASE_DIR, "hermes_guard.sh")
HERMES_HOME = os.path.expanduser(os.environ.get("HERMES_HOME",
    os.environ.get("HERMES_DIR", "~/.hermes")))  # BUG-B fix: 統一使用 HERMES_HOME，向後相容 HERMES_DIR


def run_diagnostic():
    """環境自檢：啟動時驗證必要元件"""
    issues = []
    if not os.path.exists(GUARD_SH):
        issues.append(f"hermes_guard.sh 未在 {GUARD_SH} 找到。請執行 setup.sh")
    elif not os.access(GUARD_SH, os.X_OK):
        issues.append(f"hermes_guard.sh 無執行權限。請執行 chmod +x {GUARD_SH}")

    if not os.path.exists(HERMES_HOME):
        issues.append(f"{HERMES_HOME} 目錄不存在。請執行 setup.sh")
    else:
        pitfalls = os.path.join(HERMES_HOME, "self_evolution", "pitfalls.json")
        if not os.path.exists(pitfalls):
            issues.append(f"pitfalls.json 未在 {HERMES_HOME}/self_evolution/ 找到。請執行 setup.sh")

    return issues


# 啟動時執行自檢
_startup_issues = run_diagnostic()
if _startup_issues:
    print("🔍 Hermes MCP Guard — 環境自檢", file=sys.stderr)
    for issue in _startup_issues:
        print(f"  ⚠️ {issue}", file=sys.stderr)
    print(
        "  💡 請執行: bash setup.sh 來完成安裝", file=sys.stderr
    )
    print("", file=sys.stderr)

# FIX #7: 將啟動問題存成可在 tool 回應中附帶的警告
_STARTUP_WARNING = (
    "\n\n⚠️ [環境警告] 啟動時偵測到問題，部分功能可能失效：\n"
    + "\n".join(f"  - {i}" for i in _startup_issues)
    + "\n請執行 bash setup.sh 完成安裝。"
) if _startup_issues else ""


# ═══════════════════════════════════════════════════════
# FastMCP Server
# ═══════════════════════════════════════════════════════

mcp = FastMCP("Hermes-Guard", dependencies=["mcp"])


def run_guard_cli(action: str, *args) -> subprocess.CompletedProcess:
    """執行底層核心防禦引擎"""
    if not os.path.exists(GUARD_SH):
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr=(
                f"Error: 底層防禦引擎未在 {GUARD_SH} 找到。\n"
                "請先執行 bash setup.sh 完成安裝。"
            ),
        )
    cmd = ["bash", GUARD_SH, action] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


# ═══════════════════════════════════════════════════════
# MCP Tools
# ═══════════════════════════════════════════════════════

@mcp.tool()
def execute_command(command: str) -> str:
    """
    [安全全武裝執行器] 在受 Hermes 防禦網保護的沙盒思維下執行 Ubuntu 終端機指令。
    所有指令執行前，皆會通過 Layer 1 靜態程式碼審查與知識圖譜預檢，
    在 0 毫秒、0 Token 的情況下阻擋裸奔的 json.loads()、連接埠衝突或記憶體溢出風險。

    Args:
        command: 要執行的完整終端機指令 (例如: "python3 app.py --port 8000")
    """
    _check_cooldown()

    # FIX #1: 不再用 shlex.split 展開，直接把完整字串以 "shell" op_type 傳入，
    # 避免 hermes_guard.sh wrap 段把第一個 token 誤認成 OP。
    result = run_guard_cli("wrap", "shell", command)

    if result.returncode != 0:
        return (
            f"⛔ [防禦網執行攔截/異常]\n"
            f"============ STDERR ============\n{result.stderr}\n"
            f"============ STDOUT ============\n{result.stdout}"
            + _STARTUP_WARNING  # FIX #7
        )

    # FIX #9: 成功時也附上 stderr（部分工具如 pip/ffmpeg 重要訊息在 stderr）
    output = f"✅ [執行成功]:\n{result.stdout}"
    if result.stderr.strip():
        output += f"\n[stderr]:\n{result.stderr}"
    output += _STARTUP_WARNING  # FIX #7
    return output


@mcp.tool()
def kill_resource(target: str) -> str:
    """
    [資源狙擊手] 當 Agent 發現自己把 VRAM 塞爆、進程卡死，或連接埠被佔用導致失敗時呼叫。
    此工具具備 Linux 三層優雅降級清理機制 (SIGTERM -> 核心等待 -> SIGKILL)。

    Args:
        target: 可以是卡住的 PID、連接埠號碼 (如 '8000')、或進程名稱 (如 'uvicorn')
    """
    _check_cooldown()
    
    # 🛡️ P-1: 防自殺保護名單 — 絕對不能終止的系統關鍵進程
    CRITICAL_PROCS = [
        "hermes-gateway", "hermes_cli",        # Hermes 主程序 (Telegram 連線)
        "tailscaled", "tailscale",              # VPN 通道
        "ngrok",                                 # SSH 備援通道
        "sshd",                                  # SSH daemon
        "systemd", "systemd-logind",             # init system
        "hermes_mcp.py",                         # Guard 自身
    ]
    resolved_target = target.strip()
    
    # 檢查目標是否為保護名單內的進程
    for protected in CRITICAL_PROCS:
        if resolved_target == protected or resolved_target.startswith(protected):
            return (
                f"🛡️ [防自殺保護] 拒絕終止系統關鍵進程 '{resolved_target}'。\n"
                f"此進程 ({protected}) 屬於系統命脈保護名單，終止將導致 Telegram/網路斷線。\n"
                f"若確定需要操作，請手動以其他方式處理。"
            )
    
    # 🛡️ M-2 fix: 支援以 port 號碼或進程名稱終止，而非只接受 PID
    import shlex
    resolved_target = target.strip()
    
    # 嘗試 1: 純數字 → 當作 PID
    if resolved_target.isdigit():
        result = run_guard_cli("kill", resolved_target)
        if result.returncode != 0:
            return f"❌ 資源終止失敗:\n{result.stderr}" + _STARTUP_WARNING
        return f"🎯 資源清理完畢:\n{result.stdout}"
    
    # 嘗試 2: 可能是 port 號碼 (1-65535) → 找出佔用該 port 的 PID
    try:
        port_num = int(resolved_target)
        if 1 <= port_num <= 65535:
            r = subprocess.run(
                ["ss", "-tlnp"], capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.split("\n"):
                if f":{resolved_target}" in line:
                    import re as _re
                    pid_match = _re.search(r'pid=(\d+)', line)
                    if pid_match:
                        pid = pid_match.group(1)
                        result = run_guard_cli("kill", pid)
                        if result.returncode == 0:
                            return f"🎯 已釋放 Port {resolved_target} (PID {pid}):\n{result.stdout}"
            return f"⚠️ 找不到佔用 Port {resolved_target} 的進程，可能已被釋放。"
    except ValueError:
        pass
    
    # 嘗試 3: 進程名稱 → pgrep 找出 PID
    r = subprocess.run(
        ["pgrep", "-x", shlex.quote(resolved_target) if not resolved_target.isalnum() else resolved_target],
        capture_output=True, text=True, timeout=5
    )
    if r.returncode == 0 and r.stdout.strip():
        pids = r.stdout.strip().split("\n")
        results = []
        for pid in pids[:5]:  # 最多殺 5 個匹配進程
            result = run_guard_cli("kill", pid)
            results.append(f"  PID {pid}: {result.stdout.strip() if result.returncode == 0 else result.stderr.strip()}")
        return f"🎯 已針對進程 '{resolved_target}' 清理 {len(pids)} 個實例:\n" + "\n".join(results)
    
    return f"❌ 找不到名為 '{resolved_target}' 的進程，也無法解析為有效 PID 或 Port 號碼。\n請確認進程名稱 (如 uvicorn) 或 Port 號碼 (如 8000) 是否正確。"


@mcp.tool()
def register_new_antibody(error_pattern: str, description: str, remediation: str) -> str:
    """
    [自我進化介面] 當 Agent 遇到未知的系統錯誤且克服後，可將此經驗轉錄進 pitfalls.json。
    下次再執行相同特徵的錯誤指令時，系統將實作全自動免疫與階梯式自動修復。

    Args:
        error_pattern: 觸發錯誤的關鍵字串特徵 (例如: "externally-managed-environment")
        description:   此錯誤成因的簡短系統描述
        remediation:   提供給未來自己或人類的修復引導指引
    """
    _check_cooldown()

    # FIX #10: 清洗 error_pattern，避免 shell injection
    # 移除換行、null byte、及危險 shell metachar
    import re
    for field_name, field_val in [("error_pattern", error_pattern),
                                   ("description", description),
                                   ("remediation", remediation)]:
        if re.search(r'[\x00\n\r`$\\|;&<>]', field_val):
            return (
                f"❌ 輸入欄位 '{field_name}' 包含不允許的特殊字元（換行、shell metachar 等）。"
                "請移除後重試。"
            )

    result = run_guard_cli("register", error_pattern, description, remediation)
    if result.returncode != 0:
        return f"❌ 轉錄新抗體失敗:\n{result.stderr}"
    return f"🧬 自我進化成功！新抗體已成功部署至 pitfalls.json:\n{result.stdout}"


@mcp.tool()
def inspect_system_health() -> str:
    """
    [系統資源全面觀測] 抓取當前 Linux 系統的 CPU 負載、記憶體水位、磁碟剩餘空間。
    當 Agent 準備啟動大型本機模型 (如 Llama 3/DeepSeek) 前，應用於預檢硬體極限。
    """
    _check_cooldown()
    result = run_guard_cli("inspect")
    if result.returncode != 0:
        return f"❌ 無法獲取系統狀態:\n{result.stderr}" + _STARTUP_WARNING
    return result.stdout


@mcp.tool()
def get_active_defense_rules() -> str:
    """
    [防禦網透明度面板] 查閱當前系統已啟用的所有免疫抗體清單。
    讓使用者了解哪些錯誤已被系統自動攔截，提供完全的控制感與透明感。
    """
    _check_cooldown()
    result = run_guard_cli("list")
    if result.returncode != 0:
        return f"❌ 無法讀取防禦網:\n{result.stderr}"
    try:
        data = json.loads(result.stdout)
        lines = [
            f"🛡️ 防禦網狀態 — {data['total']} 條抗體",
            f"  auto (自主學習): {data.get('auto', 0)}",
            f"  manual (手動部署): {data.get('manual', 0)}",
            "",
        ]
        for p in data.get("pitfalls", []):
            gc = "🔒" if p.get("guard_check") else "  "
            # FIX #5: 用 .get() 取代直接 key access，避免 KeyError crash
            pid   = p.get("id", "unknown")
            sev   = p.get("severity", "unknown")
            desc  = p.get("description", "")[:60]
            lines.append(f"  {gc} {pid:25s} [{sev:8s}] {desc}")
        return "\n".join(lines)
    except json.JSONDecodeError:
        return f"📋 防禦網原始輸出:\n{result.stdout}"


@mcp.tool()
def cleanup_all() -> str:
    """
    [環境清理] 釋放所有由 hermes-guard 啟動的子行程，清理殭屍進程與孤兒 Port。
    在完成一輪任務後呼叫此工具，確保系統資源不洩漏。

    清理項目：
    1. 所有由 hermes_guard.sh 啟動的子行程
    2. 孤立的背景服務（若 active_services.json 存在）
    3. 逾時的暫存資源
    """
    _check_cooldown()
    # FIX #3: signal 已在頂層 import，此處不再重複 import

    results = []

    # 1. 清理 hermes_guard 相關子行程（排除 MCP server 自身）
    try:
        # 🛡️ M-3 fix: 鎖緊匹配範圍，排除 MCP server 自身 PID
        current_pid = str(os.getpid())
        r = subprocess.run(
            ["pkill", "-f", "hermes_guard (spawn|wrap|check)"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            results.append("🧹 已清理 hermes_guard 子行程")
        else:
            results.append("✅ 無殘留的 hermes_guard 子行程")
    except Exception as e:
        results.append(f"⚠️ 清理行程時發生問題: {e}")

    # 2. 清理孤立的服務註冊表（若有）
    svc_reg = os.path.join(HERMES_HOME, "self_evolution", "active_services.json")
    if os.path.exists(svc_reg):
        try:
            with open(svc_reg) as f:
                services = json.load(f)
            active = [s for s in services if s.get("status") == "active"]
            # 🛡️ L-3 fix: 先收集所有 PID，批次發送 SIGTERM，最後再一次性等待
            sigtermed = []
            for svc in active:
                pid = svc.get("pid")
                alias = svc.get("alias", pid)
                if pid:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        sigtermed.append((pid, alias))
                        results.append(f"🛑 已送出 SIGTERM：{alias} (PID: {pid})")
                    except ProcessLookupError:
                        results.append(f"💤 服務 {alias} (PID: {pid}) 已不存在")
                    except Exception as e:
                        results.append(f"⚠️ 無法終止 {alias}: {e}")
            
            # 一次性等待 3 秒，而非每個服務各等 3 秒
            if sigtermed:
                time.sleep(3)
                for pid, alias in sigtermed:
                    try:
                        os.kill(pid, 0)  # 進程還活著
                        os.kill(pid, signal.SIGKILL)
                        results.append(f"💥 SIGTERM 無效，已強制 SIGKILL：{alias} (PID: {pid})")
                    except ProcessLookupError:
                        pass  # SIGTERM 成功，已在上面記錄
                    except Exception:
                        pass

            if active:
                results.append(f"📋 共處理 {len(active)} 個註冊服務")
        except Exception as e:
            results.append(f"⚠️ 讀取服務註冊表失敗: {e}")

    results.append("✨ 環境清理完成。")
    return "\n".join(results)


if __name__ == "__main__":
    mcp.run(transport='stdio')
