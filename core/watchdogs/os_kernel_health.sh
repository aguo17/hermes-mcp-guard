#!/bin/bash
# ==============================================================================
# Hermes Phase 1 Watchdog: os_kernel_health.sh
# 防禦目標：核心崩潰、資源耗盡 (inode, Zombie, FS-ro, FD, oops, entropy)
# ==============================================================================

# ------------------------------------------------------------------------------
# [跨平台相容性防護] Graceful Degradation
# ------------------------------------------------------------------------------
if [ "$(uname -s)" != "Linux" ]; then
    # 非 Linux 系統 (如 macOS) 缺乏 /proc 系統與特定的 Kernel 機制。
    # 為了貫徹「Silent unless alert」原則，這裡直接以健康代碼 (0) 靜默退出，
    # 讓 macOS 用戶自動降級為僅依賴 Userland 的 Linter 防禦。
    exit 0
fi

ALERT=0
ALERT_LEVEL=""  # critical / high / medium
REPORT=""

# ─── 1. Inode 監控 ───────────────────────────────────────────
# df -i 檢查 inode 使用率。inode 用完 = 有空間也無法寫檔。
INODE_PCT=$(df -i / | awk 'NR==2 {gsub(/%/,""); print $5}')
if [ "$INODE_PCT" -gt 90 ] 2>/dev/null; then
    ALERT=1
    ALERT_LEVEL="critical"
    REPORT+="🔴 inode 使用率 ${INODE_PCT}%（>90%），即將無法建立新檔！\n"
    REPORT+="   建議：find / -xdev -type f -size 0 -delete 清理空檔\n"
elif [ "$INODE_PCT" -gt 80 ] 2>/dev/null; then
    ALERT=1
    ALERT_LEVEL="high"
    REPORT+="🟡 inode 使用率 ${INODE_PCT}%（>80%），建議關注\n"
fi

# ─── 2. 檔案系統唯讀檢查 ─────────────────────────────────────
# 排除 snap/tmpfs/sysfs 等正常的 ro 掛載，只關注 ext4/xfs/btrfs 的異常 ro
RO_MOUNTS=$(grep -E "\sro[\s,]" /proc/mounts 2>/dev/null \
    | grep -v "snap\|tmpfs\|sysfs\|proc\|devpts\|cgroup\|pstore\|squashfs\|iso9660\|securityfs\|efivarfs\|fusectl\|configfs\|debugfs\|tracefs\|hugetlbfs\|mqueue\|bpf")

if [ -n "$RO_MOUNTS" ]; then
    ALERT=1
    ALERT_LEVEL="critical"
    REPORT+="🔴 偵測到異常唯讀掛載（可能是核心級檔案系統損壞）！\n"
    REPORT+="   異常掛載點：\n"
    while IFS= read -r line; do
        REPORT+="   $(echo "$line" | awk '{print $2, $1, $3}')\n"
    done <<< "$RO_MOUNTS"
    REPORT+="   立即檢查：dmesg | tail -50 查看 I/O error\n"
fi

# ─── 3. Zombie 程序堆積 ──────────────────────────────────────
ZOMBIE_COUNT=$(ps aux 2>/dev/null | awk '{if($8=="Z") print}' | wc -l)
if [ "$ZOMBIE_COUNT" -gt 50 ] 2>/dev/null; then
    ALERT=1
    ALERT_LEVEL="high"
    REPORT+="🔴 Zombie 程序堆積：${ZOMBIE_COUNT} 個（>50）\n"
    REPORT+="   Zombie 列表：\n"
    ZOMBIE_LIST=$(ps aux 2>/dev/null | awk '{if($8=="Z") printf "  PID=%s PPID=%s CMD=%s\n", $2, $3, $11}' | head -10)
    REPORT+="$ZOMBIE_LIST\n"
    REPORT+="   建議：檢查 PPID 對應的父程序是否未正確 wait()\n"
elif [ "$ZOMBIE_COUNT" -gt 20 ] 2>/dev/null; then
    ALERT=1
    ALERT_LEVEL="medium"
    REPORT+="🟡 Zombie 程序累積：${ZOMBIE_COUNT} 個（>20）\n"
    ZOMBIE_LIST=$(ps aux 2>/dev/null | awk '{if($8=="Z") printf "  PID=%s PPID=%s CMD=%s\n", $2, $3, $11}' | head -10)
    REPORT+="$ZOMBIE_LIST\n"
    REPORT+="   建議：檢查 PPID 對應的父程序是否未正確 wait()\n"
fi

# ─── 4. File Descriptor 壓力 ─────────────────────────────────
FD_USED=$(awk '{print $1}' /proc/sys/fs/file-nr 2>/dev/null)
# file-max 可能是 LLONG_MAX（無限制），改用絕對值判斷
if [ "$FD_USED" -gt 100000 ] 2>/dev/null; then
    ALERT=1
    ALERT_LEVEL="high"
    REPORT+="🔴 File Descriptor 使用量過高：${FD_USED} 個（>100000）\n"
    REPORT+="   建議：檢查是否有程序 FD 洩漏 (lsof | wc -l)\n"
elif [ "$FD_USED" -gt 50000 ] 2>/dev/null; then
    ALERT=1
    ALERT_LEVEL="medium"
    REPORT+="🟡 FD 使用量偏高：${FD_USED} 個（>50000）\n"
fi

# ─── 5. Kernel Oops / Panic ───────────────────────────────────
# 只檢查本次開機以來的 kernel oops（避免歷史雜訊）
OOPS_COUNT=$(dmesg 2>/dev/null | grep -ci "oops\|BUG:\|Kernel panic\|general protection fault")
if [ "$OOPS_COUNT" -gt 0 ] 2>/dev/null; then
    ALERT=1
    ALERT_LEVEL="critical"
    REPORT+="🔴 核心級異常偵測：${OOPS_COUNT} 次 kernel oops/BUG！\n"
    REPORT+="   詳細：\n"
    dmesg 2>/dev/null | grep -i "oops\|BUG:\|Kernel panic\|general protection fault" | tail -5 | while IFS= read -r line; do
        REPORT+="   ${line}\n"
    done
    REPORT+="   這可能導致系統不穩定或靜默資料損毀。\n"
fi

# ─── 6. 系統熵池 ─────────────────────────────────────────────
ENTROPY=$(cat /proc/sys/kernel/random/entropy_avail 2>/dev/null)
if [ -n "$ENTROPY" ] && [ "$ENTROPY" -lt 100 ] 2>/dev/null; then
    ALERT=1
    ALERT_LEVEL="medium"
    REPORT+="🟡 系統熵不足：${ENTROPY} bits（<100），TLS/DH 可能阻塞\n"
    REPORT+="   建議：apt install haveged -y && systemctl enable --now haveged\n"
fi

# ═══════════════════════════════════════════════════════════════
#  Phase 2: 感官系統 (網路) 與排泄系統 (日誌 IO)
# ═══════════════════════════════════════════════════════════════

# ─── 7. DNS 解析可用性 ─────────────────────────────────────────
# 認知隔離：DNS 異常 → Agent 呼叫 API 會 Hang 而非報錯
RESOLV_OK=true

# 檢查 systemd-resolved 是否存活
if command -v systemctl &>/dev/null; then
    RESOLVED_STATE=$(systemctl is-active systemd-resolved 2>/dev/null)
    if [ "$RESOLVED_STATE" != "active" ]; then
        RESOLV_OK=false
        ALERT=1
        ALERT_LEVEL="critical"
        REPORT+="🔴 systemd-resolved 未運行（狀態：${RESOLVED_STATE:-unknown}）！\n"
        REPORT+="   所有 DNS 解析已停擺，API 呼叫將全數阻塞。\n"
        REPORT+="   立即執行：systemctl restart systemd-resolved\n"
    fi
fi

# 檢查 /etc/resolv.conf 是否有 nameserver
if [ -f /etc/resolv.conf ]; then
    if ! grep -q "^nameserver" /etc/resolv.conf 2>/dev/null; then
        RESOLV_OK=false
        ALERT=1
        ALERT_LEVEL="critical"
        REPORT+="🔴 /etc/resolv.conf 無 nameserver 記錄！DNS 完全失效。\n"
    fi
else
    RESOLV_OK=false
    ALERT=1
    ALERT_LEVEL="critical"
    REPORT+="🔴 /etc/resolv.conf 不存在！DNS 解析已完全中斷。\n"
fi

# 輕量解析測試（僅在基礎設施正常時執行，避免無謂 timeout）
if $RESOLV_OK; then
    if ! getent hosts google.com &>/dev/null; then
        ALERT=1
        ALERT_LEVEL="high"
        REPORT+="🔴 DNS 解析測試失敗：無法解析 google.com\n"
        REPORT+="   上游 DNS 可能已失效，API 呼叫將逾時。\n"
        REPORT+="   檢查：resolvectl status | grep 'DNS Server'\n"
    fi
fi

# ─── 8. 網卡 Link 狀態 ─────────────────────────────────────────
# 直接讀取 /sys/class/net/*/operstate — 0 網路延遲、純核心層檢測
# 跳過 veth (Docker 虛擬)、lo (迴環)、tailscale (隧道)、docker 橋接
PHYSICAL_DOWN=""
for iface in $(ls /sys/class/net/ 2>/dev/null); do
    case "$iface" in
        lo|veth*|tailscale*|docker*|br-*) continue ;;
    esac

    OPERSTATE=$(cat /sys/class/net/$iface/operstate 2>/dev/null)
    CARRIER=$(cat /sys/class/net/$iface/carrier 2>/dev/null)

    if [ "$OPERSTATE" = "down" ] && [ "$CARRIER" = "0" ]; then
        PHYSICAL_DOWN="$PHYSICAL_DOWN $iface"
    fi
done

if [ -n "$PHYSICAL_DOWN" ]; then
    ALERT=1
    ALERT_LEVEL="critical"
    REPORT+="🔴 實體網卡 Link Down：$(echo $PHYSICAL_DOWN | xargs)\n"
    REPORT+="   網線已拔除或交換器埠口關閉。系統對外通訊完全中斷。\n"
    REPORT+="   檢查：ip link show 確認實體連線狀態\n"
fi

# 全面斷網偵測：所有非 lo 介面全數 down
ALL_DOWN=true
for iface in $(ls /sys/class/net/ 2>/dev/null); do
    [ "$iface" = "lo" ] && continue
    STATE=$(cat /sys/class/net/$iface/operstate 2>/dev/null)
    if [ "$STATE" = "up" ] || [ "$STATE" = "unknown" ]; then
        ALL_DOWN=false
        break
    fi
done

if $ALL_DOWN; then
    ALERT=1
    ALERT_LEVEL="critical"
    REPORT+="🔴 全面斷網：所有非 lo 網卡皆為 down 狀態！\n"
fi

# ─── 9. Journald 日誌空間 ─────────────────────────────────────
# 日誌風暴會吃光 I/O 效能與磁碟空間，卻常被 df -h 忽略
# 🦅 SysAdmin 洞察：du -sm 直接掃描實體檔案，比 journalctl --disk-usage 快數十倍
# （journalctl 在日誌達數百萬行時會卡住數秒並拉高 CPU）
if [ -d "/var/log/journal" ]; then
    JOURNAL_SIZE_MB=$(du -sm /var/log/journal 2>/dev/null | awk '{print $1}')

    if [ -n "$JOURNAL_SIZE_MB" ] && [ "$JOURNAL_SIZE_MB" -ge 2048 ] 2>/dev/null; then
        ALERT=1
        ALERT_LEVEL="high"
        REPORT+="🔴 Journald 日誌暴走：${JOURNAL_SIZE_MB}MB（>2GB）！\n"
        REPORT+="   I/O 效能可能已被拖垮，且可能吃光 /var/log 分割區。\n"
        REPORT+="   立即：journalctl --vacuum-size=500M\n"
        REPORT+="   永久：/etc/systemd/journald.conf 設定 SystemMaxUse=500M\n"
    elif [ -n "$JOURNAL_SIZE_MB" ] && [ "$JOURNAL_SIZE_MB" -ge 1024 ] 2>/dev/null; then
        ALERT=1
        ALERT_LEVEL="medium"
        REPORT+="🟡 Journald 日誌偏高：${JOURNAL_SIZE_MB}MB（>1GB）\n"
        REPORT+="   建議：檢查是否為錯誤日誌風暴 (journalctl -p 3 -xb)\n"
    fi
fi

# ─── 輸出 ─────────────────────────────────────────────────────
if [ "$ALERT" -eq 1 ]; then
    echo "╔══════════════════════════════════════════════╗"
    echo "║  🐧 OS 核心層健康警報 (Phase 1+2)            ║"
    echo "║  等級: ${ALERT_LEVEL}                                ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    echo -e "$REPORT"
    echo "---"
    echo "系統概況："
    echo "  inode: $(df -i / | awk 'NR==2 {print $5}')"
    echo "  zombie: ${ZOMBIE_COUNT}"
    echo "  fd_used: ${FD_USED}"
    echo "  oops: ${OOPS_COUNT}"
    echo "  entropy: ${ENTROPY:-N/A}"
    echo "  dns: $(systemctl is-active systemd-resolved 2>/dev/null || echo N/A)"
    echo "  nic: $(cat /sys/class/net/eno1/operstate 2>/dev/null || echo N/A)"
    echo "  journald: ${JOURNAL_SIZE_MB:-N/A}MB"
fi
