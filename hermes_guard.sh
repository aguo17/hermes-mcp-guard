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

# FIX #8: Python 不存在時給出友善錯誤，而非空字串展開
if [ -z "$PYTHON" ]; then
  echo '{"error":"找不到 Python 3 直譯器，請先安裝 python3"}' >&2
  exit 1
fi

case "$1" in
  wrap)
    shift
    # FIX #2 + #1:
    # 舊版：OP="${1:-shell}"; shift; CMD="$*"
    #   → 問題：Python 側用 shlex.split 展開後，第一個 token 會被誤吃成 OP，
    #           且 $* 會丟失引號邊界。
    # 新版：OP 直接固定為 $1（由呼叫方明確傳入 "shell"），
    #       CMD 取 $2，保留完整字串，以 "$CMD" 單一引數傳給 Python engine。
    OP="${1:-shell}"
    shift
    CMD="${1:-}"
    [ -z "$CMD" ] && { echo '{"error":"Usage: hermes_guard.sh wrap <op_type> <command_string>"}'; exit 1; }
    # 用 -- 分隔，避免 CMD 內容被 Python argparse 誤解為 flag
    cd "$CORE_DIR" && "$PYTHON" "$ENGINE" wrap "$OP" -- "$CMD"
    ;;

  kill)
    shift
    TARGET="${1:-}"
    [ -z "$TARGET" ] && { echo '{"error":"Usage: hermes_guard.sh kill <pid|port|name>"}'; exit 1; }
    FORCE="${2:-}"
    if [ "$FORCE" = "force" ] || [ "$FORCE" = "true" ]; then
      cd "$CORE_DIR" && "$PYTHON" "$ENGINE" kill "$TARGET" true
    else
      cd "$CORE_DIR" && "$PYTHON" "$ENGINE" kill "$TARGET"
    fi
    ;;

  register)
    shift
    PATTERN="${1:-}"
    DESC="${2:-}"
    REMEDIATION="${3:-}"
    [ -z "$PATTERN" ] && { echo '{"error":"Usage: hermes_guard.sh register <pattern> <desc> <fix>"}'; exit 1; }
    cd "$CORE_DIR" && "$PYTHON" "$ENGINE" register "$PATTERN" "$DESC" "$REMEDIATION"
    ;;

  inspect)
    cd "$CORE_DIR" && "$PYTHON" "$ENGINE" inspect all
    ;;

  list)
    cd "$CORE_DIR" && "$PYTHON" "$ENGINE" list
    ;;

  *)
    echo "Hermes Guard CLI — 開源版"
    echo "用法: hermes_guard.sh {wrap|kill|register|inspect|list} [args...]"
    exit 1
    ;;
esac
