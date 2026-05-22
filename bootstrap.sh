#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  Hermes MCP Guard — Bootstrap / Cron Installer
#  一鍵完成：依賴安裝 → 目錄建立 → Watchdog 排程注入
#
#  用法：bash bootstrap.sh
#  冪等性：可重複執行，不會重複寫入重複的 cron job
# ═══════════════════════════════════════════════════════════════
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHDOG_DIR="$SCRIPT_DIR/core/watchdogs"
LOG_DIR="$SCRIPT_DIR/logs"
IS_LINUX=false
[ "$(uname -s)" = "Linux" ] && IS_LINUX=true

echo "╔══════════════════════════════════════════╗"
echo "║  🛡️  Hermes MCP Guard — 啟動安裝         ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "📍 專案目錄：$SCRIPT_DIR"
echo "🐧 作業系統：$(uname -s)"
echo ""

# ─── Step 1: 依賴安裝 ─────────────────────────────────────
echo "📦 Step 1/4: 安裝 Python 依賴..."
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    pip install --break-system-packages -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || \
    pip3 install --break-system-packages -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || \
    python3 -m pip install --break-system-packages -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || \
    pip install -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || \
    pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || \
    python3 -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || {
        echo "   ⚠️  自動 pip 安裝失敗，請手動執行："
        echo "   pip install --break-system-packages -r $SCRIPT_DIR/requirements.txt"
    }
else
    echo "   ⚠️  找不到 requirements.txt，跳過。"
fi
echo "   ✅ 完成"
echo ""

# ─── Step 2: 目錄建立 ─────────────────────────────────────
echo "📁 Step 2/4: 建立必要目錄..."
mkdir -p "$LOG_DIR"
echo "   ✅ 日誌目錄：$LOG_DIR"
echo ""

# ─── Step 3: Cron 排程注入 ─────────────────────────────────
echo "⏰ Step 3/4: 設定 Watchdog 排程..."

CRON_TMP=$(mktemp)
crontab -l 2>/dev/null > "$CRON_TMP" || true

CRON_ADDED=0

add_cron_job() {
    local schedule="$1"
    local script_path="$2"
    local description="$3"

    # 避免重複寫入（冪等性）
    if grep -qF "$script_path" "$CRON_TMP" 2>/dev/null; then
        echo "   ⏭️  已存在：$description"
        return
    fi

    echo "$schedule bash $script_path >> $LOG_DIR/cron_$(basename "$script_path" .sh).log 2>&1" >> "$CRON_TMP"
    echo "   ✅ 已新增：$description"
    CRON_ADDED=$((CRON_ADDED + 1))
}

# Phase 2 感官層 Watchdog（跨平台：DNS 檢測 macOS 也支援）
# NIC 和 Journald 區塊在腳本內已有 OS 判斷，非 Linux 會自動略過
add_cron_job "*/30 * * * *" "$WATCHDOG_DIR/os_network_health.sh" \
    "Phase 2 灰度失效預警 (NIC/DNS/Journald) — 每 30 分鐘"

# Phase 1 核心層 Watchdog（僅 Linux）
if $IS_LINUX; then
    add_cron_job "*/30 * * * *" "$WATCHDOG_DIR/os_kernel_health.sh" \
        "Phase 1 核心層檢測 (inode/FS/Zombie/FD/oops) — 每 30 分鐘"
else
    echo "   ⏭️  略過 os_kernel_health.sh（macOS 不支援 Linux 核心層檢測）"
fi

# 知識圖譜反思 Worker（每日 03:00）
add_cron_job "0 3 * * *" "$WATCHDOG_DIR/reflect_daily.sh" \
    "知識圖譜夜間反思 — 每日 03:00"

echo ""

if [ "$CRON_ADDED" -gt 0 ]; then
    crontab "$CRON_TMP"
    echo "   🎉 已寫入 $CRON_ADDED 個 Cron Job！"
else
    echo "   ℹ️  所有排程已存在，無需新增。"
fi

rm -f "$CRON_TMP"
echo ""

# ─── Step 4: 驗證摘要 ─────────────────────────────────────
echo "📋 Step 4/4: 安裝驗證"
echo "──────────────────────────────────────────────"
echo ""

# Python 依賴檢查
echo "🐍 Python 依賴："
python3 -c "import mcp; print('   ✅ mcp', mcp.__version__ if hasattr(mcp,'__version__') else '')" 2>/dev/null || echo "   ⚠️  mcp 未安裝"
python3 -c "import psutil; print('   ✅ psutil', psutil.__version__)" 2>/dev/null || echo "   ⚠️  psutil 未安裝（部分功能需要）"
echo ""

# Watchdog 存在性檢查
echo "🛡️  Watchdog："
for w in os_kernel_health.sh os_network_health.sh reflect_daily.sh; do
    if [ -x "$WATCHDOG_DIR/$w" ]; then
        echo "   ✅ $w"
    else
        echo "   ❌ $w 遺失或無執行權限"
    fi
done
echo ""

# 手動觸發測試（確認不會報錯）
echo "🧪 快速煙霧測試："
if $IS_LINUX; then
    bash "$WATCHDOG_DIR/os_kernel_health.sh" && echo "   ✅ os_kernel_health.sh 正常" || echo "   ⚠️  os_kernel_health.sh 有警報（可能系統確有異常）"
fi
bash "$WATCHDOG_DIR/os_network_health.sh" && echo "   ✅ os_network_health.sh 正常" || echo "   ⚠️  os_network_health.sh 有警報（可能系統確有異常）"
echo ""

echo "╔══════════════════════════════════════════╗"
echo "║  ✅ Hermes MCP Guard 安裝完成！           ║"
echo "║                                          ║"
echo "║  已啟用 Watchdog：                        ║"
if $IS_LINUX; then
echo "║  • os_kernel_health.sh  每 30 分鐘       ║"
fi
echo "║  • os_network_health.sh 每 30 分鐘       ║"
echo "║  • reflect_daily.sh     每日 03:00       ║"
echo "║                                          ║"
echo "║  日誌目錄：$LOG_DIR"
echo "║                                          ║"
echo "║  下一步：設定 MCP Client                 ║"
echo "║  詳見 README.md                          ║"
echo "╚══════════════════════════════════════════╝"
