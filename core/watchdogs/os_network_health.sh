#!/bin/bash
# ==============================================================================
# Hermes Phase 2 Watchdog: os_network_health.sh
# 防禦目標：灰度失效 (Gray Failure) - 認知隔離、物理斷線、慢性窒息
# 運行哲學：Silent unless alert (0 輸出代表健康)
#
# ⚠️ NIC 和 Journald 檢測依賴 Linux 核心機制。macOS 使用者：
#    腳本會自動略過 Linux 專屬檢測，僅執行跨平台 DNS 解析測試。
# ==============================================================================

# 🦅 跨系統偵測
IS_LINUX=false
[ "$(uname -s)" = "Linux" ] && IS_LINUX=true

ALERTS=""

# ------------------------------------------------------------------------------
# 1. NIC 網卡狀態 (物理/虛擬連線中斷) -> 0ms 核心層讀取
# ------------------------------------------------------------------------------
# 直接讀取 Kernel sysfs，避開 ifconfig/ip 指令的開銷。
# 過濾掉 lo (本機迴環)、docker、veth 等虛擬網卡，只針對實體或主要網卡。
for iface_path in /sys/class/net/*; do
    iface=$(basename "$iface_path")
    
    # 過濾無需監控的虛擬介面
    if [[ "$iface" == "lo" || "$iface" == veth* || "$iface" == docker* || "$iface" == br-* ]]; then
        continue
    fi

    if $IS_LINUX && [ -f "$iface_path/operstate" ]; then
        state=$(cat "$iface_path/operstate")
        if [[ "$state" == "down" ]]; then
            ALERTS+="- 🔴 [NIC] 網卡 $iface 狀態異常 (Link Down)，伺服器可能處於失聯邊緣。\n"
        fi
    fi
done

# ------------------------------------------------------------------------------
# 2. DNS 解析失敗 (認知隔離) -> 嚴格 2 秒 Timeout
# ------------------------------------------------------------------------------
# 使用原生 getent 直接呼叫 glibc 的 Name Service Switch，不依賴外部 ping。
# 如果 2 秒內無法解析，代表 systemd-resolved 或上游 DNS 已死，Agent 將產生幻覺。
if ! timeout 2 getent hosts github.com > /dev/null 2>&1; then
    ALERTS+="- 🔴 [DNS] 解析超時或失敗 (Gray Failure 發生)。Agent 將無法呼叫外部 API。\n"
fi

# ------------------------------------------------------------------------------
# 3. Journald 空間暴走 (慢性窒息) -> O(1) 空間快篩
# ------------------------------------------------------------------------------
# 避開緩慢的 journalctl --disk-usage，直接計算實體目錄大小 (MB)。
# 黃金防線：1GB 預警 (🟡)，2GB 危險 (🔴)
if [ -d "/var/log/journal" ]; then
    # 2>/dev/null 確保即使有權限變更也不會噴出無用錯誤
    JOURNAL_SIZE_MB=$(du -sm /var/log/journal 2>/dev/null | awk '{print $1}')
    
    if [ "$JOURNAL_SIZE_MB" -ge 2048 ]; then
        ALERTS+="- 🔴 [Journald] 日誌空間突破 2GB (${JOURNAL_SIZE_MB}MB)！嚴重威脅系統 IOPS。\n"
    elif [ "$JOURNAL_SIZE_MB" -ge 1024 ]; then
        ALERTS+="- 🟡 [Journald] 日誌空間突破 1GB (${JOURNAL_SIZE_MB}MB)。請檢查 SystemMaxUse 設定。\n"
    fi
fi

# ------------------------------------------------------------------------------
# 結算與發送 (與 Telegram / MCP 橋接)
# ------------------------------------------------------------------------------
if [ -n "$ALERTS" ]; then
    # 只要有輸出，Hermes 既有的 Cron 捕捉機制就會將其判定為 Alert 並推播
    echo -e "⚠️ Hermes [Phase 2] 灰度失效預警:\n$ALERTS"
    exit 1
fi

# 健康狀態，絕對無聲
exit 0
