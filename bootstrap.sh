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

# FIX M-4: 預設不自動修改系統 crontab，需明確同意。
# 用法：
#   bash bootstrap.sh            → 只裝依賴、建目錄，cron 僅顯示「將要安裝的內容」並詢問
#   bash bootstrap.sh --yes      → 非互動模式，確認安裝 cron
#   HERMES_NO_CRON=1 bash ...     → 強制略過 cron 安裝
ASSUME_YES=false
for arg in "$@"; do
    [ "$arg" = "--yes" ] || [ "$arg" = "-y" ] && ASSUME_YES=true
done

echo "╔══════════════════════════════════════════╗"
echo "║  🛡️  Hermes MCP Guard — 啟動安裝         ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "📍 專案目錄：$SCRIPT_DIR"
echo "🐧 作業系統：$(uname -s)"
echo ""

# ─── Step 1: 依賴安裝 ─────────────────────────────────────
echo "📦 Step 1/4: 安裝 Python 依賴..."
# FIX M-4: 優先使用 venv，避免污染系統 Python（--break-system-packages 僅作最後手段）
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    if [ -d "$SCRIPT_DIR/venv" ] || python3 -m venv "$SCRIPT_DIR/venv" 2>/dev/null; then
        echo "   ✅ 使用虛擬環境 $SCRIPT_DIR/venv"
        # shellcheck disable=SC1091
        source "$SCRIPT_DIR/venv/bin/activate"
        pip install -r "$SCRIPT_DIR/requirements.txt" --quiet || \
            echo "   ⚠️  venv 安裝失敗，請手動處理。"
    else
        echo "   ⚠️  無法建立 venv，改用使用者層級安裝（--user）"
        python3 -m pip install --user -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || \
        python3 -m pip install --user --break-system-packages -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || {
            echo "   ⚠️  自動安裝失敗，請手動執行（建議用 venv）："
            echo "   python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
        }
    fi
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

# FIX M-4: 修改使用者 crontab 前先取得明確同意
if [ "${HERMES_NO_CRON:-0}" = "1" ]; then
    echo "   ⏭️  HERMES_NO_CRON=1，略過所有 cron 排程安裝。"
    echo ""
    CRON_ADDED=0
else
    echo "   ℹ️  即將在你的 crontab 安裝以下排程（每 30 分鐘 / 每日 03:00）："
    echo "       - os_network_health.sh   每 30 分鐘"
    $IS_LINUX && echo "       - os_kernel_health.sh    每 30 分鐘"
    echo "       - reflect_daily.sh       每日 03:00"
    echo ""

    PROCEED_CRON=false
    if $ASSUME_YES; then
        PROCEED_CRON=true
        echo "   ✅ --yes 已指定，繼續安裝 cron。"
    else
        printf "   ❓ 是否在 crontab 安裝上述排程？[y/N] "
        read -r _ans </dev/tty 2>/dev/null || _ans="n"
        case "$_ans" in
            y|Y|yes|YES) PROCEED_CRON=true ;;
            *) echo "   ⏭️  使用者未同意，略過 cron 安裝。可日後手動執行：bash bootstrap.sh --yes" ;;
        esac
    fi

    CRON_ADDED=0
    if $PROCEED_CRON; then
        CRON_TMP=$(mktemp)
        crontab -l 2>/dev/null > "$CRON_TMP" || true

        add_cron_job() {
            local schedule="$1"
            local script_path="$2"
            local description="$3"
            if grep -qF "$script_path" "$CRON_TMP" 2>/dev/null; then
                echo "   ⏭️  已存在：$description"
                return
            fi
            echo "$schedule bash $script_path >> $LOG_DIR/cron_$(basename "$script_path" .sh).log 2>&1" >> "$CRON_TMP"
            echo "   ✅ 已新增：$description"
            CRON_ADDED=$((CRON_ADDED + 1))
        }

        add_cron_job "*/30 * * * *" "$WATCHDOG_DIR/os_network_health.sh" \
            "Phase 2 灰度失效預警 (NIC/DNS/Journald) — 每 30 分鐘"
        if $IS_LINUX; then
            add_cron_job "*/30 * * * *" "$WATCHDOG_DIR/os_kernel_health.sh" \
                "Phase 1 核心層檢測 (inode/FS/Zombie/FD/oops) — 每 30 分鐘"
        else
            echo "   ⏭️  略過 os_kernel_health.sh（macOS 不支援 Linux 核心層檢測）"
        fi
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
    fi
fi
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
