#!/usr/bin/env python3
"""
Reflection Worker — 從 evolution.log 提煉因果知識圖譜
Phase 1: Regex 提取（零 Token 消耗）
Phase 2: 可選 LLM 增強（批次送入本地模型）
"""

import json
import re
import os
import sys
from datetime import datetime
from collections import defaultdict

# ─── 路徑設定 ───
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "evolution.log")
GRAPH_FILE = os.path.join(BASE_DIR, "knowledge_graph.json")
PITFALLS_FILE = os.path.join(BASE_DIR, "pitfalls.json")
THRESHOLD = 3  # 同一關聯出現 N 次 → 觸發進化


# ═══════════════════════════════════════
#  Phase 1: Regex 提取器（零 Token）
# ═══════════════════════════════════════

def extract_edges_from_log(log_path):
    """從半結構化 evolution.log 提取因果邊緣"""
    edges = []
    lines = []
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    timestamp_re = re.compile(r"^\[([^\]]+)\]")
    wrap_re = re.compile(r"WRAP:\s*cmd=(.+?)\s+verdict=(\S+)")
    interceptor_re = re.compile(r"INTERCEPTOR_MATCH:\s*pattern=(.+?)\s+pitfall=(\S+)")
    auto_learn_re = re.compile(r"AUTO_LEARN:\s*id=(\S+)\s+desc=(.+)")
    learn_new_re = re.compile(r"LEARN_NEW:\s*id=(\S+)\s+desc=(.+)")
    linter_re = re.compile(r"LINTER_BLOCK:\s*op=(\S+)\s+blocks=\[(.+)\]")
    revoke_re = re.compile(r"REVOKE:\s*id=(\S+)\s+desc=(.+)")

    # ── Pass 1：單行提取 ──
    for i, line in enumerate(lines):
        ts_match = timestamp_re.search(line)
        ts = ts_match.group(1) if ts_match else str(i)

        # WRAP: cmd → 產出 verdict
        wm = wrap_re.search(line)
        if wm:
            cmd = wm.group(1).strip()
            verdict = wm.group(2).strip()
            if verdict != "OK":
                short_cmd = cmd.split()[0] if " " in cmd else cmd
                edges.append({
                    "source": short_cmd[:40],
                    "relation": "PRODUCES",
                    "target": f"verdict:{verdict}",
                    "context": f"cmd={cmd[:80]}",
                    "weight": 1,
                    "timestamp": ts,
                })

        # INTERCEPTOR_MATCH: error_pattern → caught by pitfall
        im = interceptor_re.search(line)
        if im:
            pattern = im.group(1).strip()[:50]
            pitfall = im.group(2).strip()
            edges.append({
                "source": f"error:{pattern}",
                "relation": "CAUGHT_BY",
                "target": f"pitfall:{pitfall}",
                "context": f"pattern={pattern}",
                "weight": 1,
                "timestamp": ts,
            })

        # AUTO_LEARN / LEARN_NEW: 新坑來自何處
        al = auto_learn_re.search(line) or learn_new_re.search(line)
        if al:
            pid = al.group(1).strip()
            desc = al.group(2).strip()[:80]
            edges.append({
                "source": "system",
                "relation": "LEARNED",
                "target": f"pitfall:{pid}",
                "context": f"desc={desc}",
                "weight": 1,
                "timestamp": ts,
            })

        # LINTER_BLOCK: 操作被預檢阻擋
        lb = linter_re.search(line)
        if lb:
            op = lb.group(1).strip()
            blocks = lb.group(2).strip()
            for pitfall_id in re.findall(r"[a-zA-Z0-9_-]+", blocks):
                edges.append({
                    "source": f"op:{op}",
                    "relation": "BLOCKED_BY",
                    "target": f"pitfall:{pitfall_id}",
                    "context": f"pre-flight block",
                    "weight": 1,
                    "timestamp": ts,
                })

        # REVOKE: 規則被撤銷
        rk = revoke_re.search(line)
        if rk:
            pid = rk.group(1).strip()
            desc = rk.group(2).strip()[:80]
            edges.append({
                "source": "system",
                "relation": "REVOKED",
                "target": f"pitfall:{pid}",
                "context": f"desc={desc}",
                "weight": 1,
                "timestamp": ts,
            })

    # ── Pass 2：因果鏈偵測（cmd → UNKNOWN_ERROR → cmd' → OK）──
    for i in range(len(lines) - 1):
        w1 = wrap_re.search(lines[i])
        w2 = wrap_re.search(lines[i + 1])
        if w1 and w2:
            cmd1 = w1.group(1).strip()
            v1 = w1.group(2).strip()
            cmd2 = w2.group(1).strip()
            v2 = w2.group(2).strip()
            # 連續：cmd1 失敗 → cmd2 成功（修復鏈）
            if v1 == "UNKNOWN_ERROR" and v2 == "OK" and cmd1 != cmd2:
                ts_match = timestamp_re.search(lines[i + 1])
                ts = ts_match.group(1) if ts_match else str(i)
                edges.append({
                    "source": f"cmd:{cmd1[:40]}",
                    "relation": "FIXED_BY",
                    "target": f"cmd:{cmd2[:40]}",
                    "context": f"自動修復鏈: {cmd1[:50]} → {cmd2[:50]}",
                    "weight": 1,
                    "timestamp": ts,
                    "is_causal_chain": True,
                })

    return edges


# ═══════════════════════════════════════
#  圖譜融合
# ═══════════════════════════════════════

def merge_into_graph(new_edges, graph_path):
    """將新邊緣合併到現有圖譜，相同 edge_key 增加權重"""
    now = datetime.now().isoformat()

    if os.path.exists(graph_path):
        with open(graph_path, "r", encoding="utf-8") as f:
            graph = json.load(f)
    else:
        graph = {
            "version": "1.0",
            "created": now,
            "nodes": {},
            "edges": {},
            "clusters": [],
            "stats": {"total_edges": 0, "total_nodes": 0, "last_extraction": None, "extraction_count": 0},
        }

    for edge in new_edges:
        src = edge["source"]
        rel = edge["relation"]
        tgt = edge["target"]
        edge_key = f"{src}-[{rel}]->{tgt}"

        # 確保節點存在
        for node_name in [src, tgt]:
            if node_name not in graph["nodes"]:
                graph["nodes"][node_name] = {
                    "first_seen": edge.get("timestamp", now),
                    "last_seen": edge.get("timestamp", now),
                    "type": node_name.split(":")[0] if ":" in node_name else "unknown",
                }
            else:
                graph["nodes"][node_name]["last_seen"] = edge.get("timestamp", now)

        # 合併邊緣
        if edge_key in graph["edges"]:
            graph["edges"][edge_key]["weight"] += 1
            graph["edges"][edge_key]["last_seen"] = edge.get("timestamp", now)
            ctx = graph["edges"][edge_key].get("context", "")
            if edge.get("context") and edge["context"] not in ctx:
                graph["edges"][edge_key]["context"] += f" | {edge['context']}"
        else:
            graph["edges"][edge_key] = {
                "source": src,
                "target": tgt,
                "relation": rel,
                "weight": 1,
                "context": edge.get("context", ""),
                "first_seen": edge.get("timestamp", now),
                "last_seen": edge.get("timestamp", now),
                "mitigated": False,
                "is_causal_chain": edge.get("is_causal_chain", False),
            }

    # 更新統計
    graph["stats"]["total_edges"] = len(graph["edges"])
    graph["stats"]["total_nodes"] = len(graph["nodes"])
    graph["stats"]["last_extraction"] = now
    graph["stats"]["extraction_count"] += 1

    # 偵測高密度 cluster
    node_degree = defaultdict(int)
    for ek, ed in graph["edges"].items():
        node_degree[ed["source"]] += 1
        node_degree[ed["target"]] += 1
    clusters = [
        {"center": node, "degree": deg}
        for node, deg in sorted(node_degree.items(), key=lambda x: -x[1])
        if deg >= 5
    ]
    graph["clusters"] = clusters[:10]

    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    return graph


# ═══════════════════════════════════════
#  觸發進化（反哺 Layer 1）
# ═══════════════════════════════════════

def trigger_evolution(graph, threshold=THRESHOLD):
    """掃描圖譜，高頻邊緣 → 建議 register"""
    alerts = []

    for edge_key, edge in graph["edges"].items():
        if edge["weight"] >= threshold and not edge.get("mitigated"):
            alerts.append({
                "edge_key": edge_key,
                "source": edge["source"],
                "target": edge["target"],
                "relation": edge["relation"],
                "weight": edge["weight"],
                "context": edge.get("context", ""),
            })

    return alerts


# ═══════════════════════════════════════
#  報表
# ═══════════════════════════════════════

def print_report(graph, new_edge_count, alerts):
    print("=" * 60)
    print("   🧠 Reflection Worker — 知識圖譜更新報告")
    print(f"   執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"\n📊 圖譜狀態:")
    print(f"   節點: {graph['stats']['total_nodes']}")
    print(f"   邊緣: {graph['stats']['total_edges']}")
    print(f"   本次新增: {new_edge_count} 條")
    print(f"   提取次數: {graph['stats']['extraction_count']}")

    # Top 5 高權重邊緣
    top_edges = sorted(graph["edges"].items(), key=lambda x: -x[1]["weight"])[:10]
    print(f"\n🔥 高權重關聯 Top 10:")
    for i, (ek, ed) in enumerate(top_edges, 1):
        causal = "🔗" if ed.get("is_causal_chain") else "  "
        print(f"  {i:2d}. {causal} [{ed['weight']:2d}x] {ed['source'][:30]} ──{ed['relation']}──▶ {ed['target'][:30]}")

    # Clusters
    if graph["clusters"]:
        print(f"\n🕸️  高密度故障核心 (degree ≥ 5):")
        for c in graph["clusters"][:5]:
            print(f"  • {c['center'][:40]}: 連接度 {c['degree']}")

    # 進化警報
    if alerts:
        print(f"\n🚨 進化警報 — 以下關聯已達閾值 ({THRESHOLD}x):")
        for a in alerts:
            print(f"  ⚠️  {a['edge_key'][:70]}")
            print(f"      權重: {a['weight']} | 建議 register: {a['target']}")
    else:
        print(f"\n✅ 無關聯達進化閾值 ({THRESHOLD}x)")

    print(f"\n📁 圖譜: {GRAPH_FILE}")


# ═══════════════════════════════════════
#  Main
# ═══════════════════════════════════════

def main():
    if not os.path.exists(LOG_FILE):
        print(f"❌ 日誌不存在: {LOG_FILE}")
        return 1

    # 1. 提取
    new_edges = extract_edges_from_log(LOG_FILE)
    print(f"📋 從 evolution.log 提取 {len(new_edges)} 條原始關聯")

    if not new_edges:
        print("ℹ️  無新關聯可提取")
        return 0

    # 2. 融合
    graph = merge_into_graph(new_edges, GRAPH_FILE)

    # 3. 進化觸發
    alerts = trigger_evolution(graph, THRESHOLD)

    # 4. 報表
    print_report(graph, len(new_edges), alerts)

    # alerts 是預期行為（這是 worker 的核心功能），exit 0 表示 worker 本身成功
    # 非零 exit 只應保留給真正的崩潰（日誌不存在等）
    return 0


if __name__ == "__main__":
    sys.exit(main())
