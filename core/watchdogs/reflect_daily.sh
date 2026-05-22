#!/bin/bash
# Reflection Worker — 每日 03:00 自動執行
# 🔧 Cron 幽靈環境防禦：強制注入使用者環境 + 絕對路徑
source $HOME/.bashrc 2>/dev/null || true
export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"

# 🦅 動態路徑：從腳本位置推算專案根目錄，擺脫 ~/.hermes/ 硬編碼
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORE_DIR="$REPO_ROOT/core"

LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/reflect_cron_$(date +%Y%m%d).log"

cd "$CORE_DIR" && /usr/bin/python3 reflect_worker.py 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

# 寫入摘要行
echo "[$(date '+%Y-%m-%d %H:%M:%S')] exit_code=$EXIT_CODE" >> "$LOG_FILE"
exit $EXIT_CODE
