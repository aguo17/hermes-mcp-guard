#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Hermes Guard CLI Bridge — 開源版
# 將 bash 介面橋接到 Python 核心引擎
# ═══════════════════════════════════════════════════════════

# ── Root 權限物理護欄 ──
if [[ $EUID -eq 0 ]]; then
   echo "❌ 安全警告：請勿以 root 權限執行 Hermes Guard。請使用一般使用者執行。" >&2
   exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CORE_DIR="$SCRIPT_DIR/core"
ENGINE="$CORE_DIR/hermes_guard.py"
PITFALLS="$CORE_DIR/pitfalls.json"

# 動態定位 Python3（優先 3.11）
PYTHON=$(command -v python3.11 || command -v python3 || command -v python)

case "$1" in
    wrap)
        shift
        OP="${1:-shell}"
        shift
        CMD="$*"
        [ -z "$CMD" ] && { echo '{"error":"Usage: hermes_guard.sh wrap <op_type> <command>"}'; exit 1; }
        cd "$CORE_DIR" && $PYTHON "$ENGINE" wrap "$OP" "$CMD"
        ;;
    kill)
        shift
        TARGET="${1:-}"
        [ -z "$TARGET" ] && { echo '{"error":"Usage: hermes_guard.sh kill <pid>"}'; exit 1; }
        FORCE="${2:-}"
        if [ "$FORCE" = "force" ] || [ "$FORCE" = "true" ]; then
            cd "$CORE_DIR" && $PYTHON "$ENGINE" kill "$TARGET" true
        else
            cd "$CORE_DIR" && $PYTHON "$ENGINE" kill "$TARGET"
        fi
        ;;
    register)
        shift
        PATTERN="${1:-}"
        DESC="${2:-}"
        REMEDIATION="${3:-}"
        [ -z "$PATTERN" ] && { echo '{"error":"Usage: hermes_guard.sh register <pattern> <desc> <fix>"}'; exit 1; }
        cd "$CORE_DIR" && $PYTHON "$ENGINE" register "$PATTERN" "$DESC" "$REMEDIATION"
        ;;
    inspect)
        cd "$CORE_DIR" && $PYTHON "$ENGINE" inspect all
        ;;
    list)
        cd "$CORE_DIR" && $PYTHON "$ENGINE" list
        ;;
    *)
        echo "Hermes Guard CLI — 開源版"
        echo "用法: hermes_guard.sh {wrap|kill|register|inspect|list} [args...]"
        exit 1
        ;;
esac
