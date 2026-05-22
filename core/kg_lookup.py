#!/usr/bin/env python3
"""
kg_lookup.py — 知識圖譜快速查表器
Layer 1 預檢：O(1) 查表，<10ms 執行
將使用者指令拆解為實體，查閱 knowledge_graph.json 中的高風險關聯
"""

import sys
import json
import re
import os

GRAPH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_graph.json")

# 🦅 優先讀取 HERMES_HOME 下的已安裝 KG（setup.sh 會複製到那），
# 確保夜間反思寫入的新知識不會因 kg_lookup 讀 repo 原始檔而被忽略
_HERMES_HOME = os.environ.get("HERMES_HOME", os.path.join(os.path.expanduser("~"), ".hermes"))
_INSTALLED_KG = os.path.join(_HERMES_HOME, "self_evolution", "knowledge_graph.json")
if os.path.exists(_INSTALLED_KG):
    GRAPH_FILE = _INSTALLED_KG
RISKY_RELATIONS = {"OCCUPIES", "OOM_KILLED", "EXCEEDS", "CRASHED_BY", "BREAKS", "PRODUCES"}
WARN_WEIGHT = 3  # 權重 ≥ N 才警告


def tokenize(command: str) -> set:
    """拆解指令為實體集合。特化 port/script/package 提取"""
    cmd_lower = command.lower()
    tokens = set(cmd_lower.split())

    # 提取 .py 腳本名
    scripts = set(re.findall(r"(\w+\.py)", cmd_lower))
    tokens.update(scripts)

    # 提取 port 號碼（80xx/90xx 範圍）
    ports = set(re.findall(r"(80\d{2}|90\d{2})", cmd_lower))
    for p in ports:
        tokens.add(f"port_{p}")

    # 提取 pip package 名
    pkg_match = re.search(r"pip\s+install\s+(\S+)", cmd_lower)
    if pkg_match:
        tokens.add(f"pkg:{pkg_match.group(1)}")

    # 提取 python/python3/python3.11
    py_match = re.findall(r"(python3?\.?\d*)", cmd_lower)
    tokens.update(py_match)

    return {t.strip().rstrip(".") for t in tokens if len(t) > 1}


def lookup(command: str, graph_path: str = GRAPH_FILE, warn_weight: int = WARN_WEIGHT):
    """查閱圖譜，回傳警告列表"""
    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            graph = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []  # 圖譜尚未建立，放行

    entities = tokenize(command)
    warnings = []
    seen_edge_keys = set()

    for edge_key, edge in graph.get("edges", {}).items():
        if edge.get("weight", 0) < warn_weight:
            continue
        if edge_key in seen_edge_keys:
            continue

        src = edge["source"]
        tgt = edge["target"]
        rel = edge.get("relation", "UNKNOWN")

        # 只關注高風險關聯
        if rel not in RISKY_RELATIONS and not edge.get("is_causal_chain"):
            # 放行 CAUGHT_BY / BLOCKED_BY / LEARNED（這些是正常防禦）
            continue

        # 節點碰撞檢查
        src_match = any(e in src.lower() for e in entities)
        tgt_match = any(e in tgt.lower() for e in entities)

        if src_match or tgt_match:
            seen_edge_keys.add(edge_key)
            ctx = edge.get("context", "")[:80]
            warnings.append(
                f"⚠️  圖譜經驗: {src[:30]} ──{rel}──▶ {tgt[:30]} "
                f"({ctx}, 發生 {edge['weight']} 次)"
            )

    return warnings


def main():
    if len(sys.argv) < 2:
        # stdin 模式
        command = sys.stdin.read().strip()
        if not command:
            return
    else:
        command = " ".join(sys.argv[1:])

    warnings = lookup(command)

    if warnings:
        print("\n".join(warnings))


if __name__ == "__main__":
    main()
