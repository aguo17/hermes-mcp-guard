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

cd "$CORE_DIR"

# 🦅 BUG-H fix: reflect_worker.py 若不存在則靜默跳過，不讓 cron job 每天爆炸
if [ ! -f "$CORE_DIR/reflect_worker.py" ]; then
    echo "[$(date)] reflect_worker.py 不存在，跳過" >> "$LOG_FILE"
    exit 0
fi

/usr/bin/python3 reflect_worker.py 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

# 寫入摘要行
echo "[$(date '+%Y-%m-%d %H:%M:%S')] exit_code=$EXIT_CODE" >> "$LOG_FILE"

# ------------------------------------------------------------------------------
# [自體代謝機制] Log Rotation
# 防止系統長期運作導致 logs/ 空間膨脹
# ------------------------------------------------------------------------------
if [ -d "$LOG_DIR" ]; then
    echo "[Log Rotation] 啟動日誌代謝，正在清理 7 天前的歷史日誌..." | tee -a "$LOG_FILE"
    # 使用 -delete 是最安全且 O(1) 的原生清理做法
    find "$LOG_DIR" -name "*.log" -type f -mtime +7 -delete 2>/dev/null
    echo "[Log Rotation] 清理完成。" | tee -a "$LOG_FILE"
fi

exit $EXIT_CODE
