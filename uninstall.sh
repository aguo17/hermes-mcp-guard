#!/bin/bash
# ==============================================================================
# Hermes MCP Guard - Uninstaller
# 負責乾淨俐落地撤除所有系統排程與捷徑，貫徹開源維運禮儀
# ==============================================================================

echo "🛑 正在啟動 Hermes MCP Guard 撤除程序..."

# 1. 清除所有的 Cron 排程
echo "🧹 [1/2] 正在清理 Cron 排程..."
if crontab -l &>/dev/null; then
    # 抓出現有排程，過濾掉包含 hermes 關鍵字的行，然後重新寫入
    crontab -l | grep -v -i 'hermes' | crontab -
    echo "   ✅ 所有 Hermes 相關的排程已安全移除。"
else
    echo "   ➖ 系統中目前沒有 crontab 紀錄，略過。"
fi

# 2. 提醒移除實體檔案
echo "📂 [2/2] 實體檔案與資料"
echo "   ⚠️ 為了保護您的知識圖譜 (knowledge_graph.json) 與歷史日誌，"
echo "   本腳本不會自動刪除您的個人檔案。"
echo "   如果您確定要完全抹除 Hermes 的所有痕跡，請手動執行以下指令："
echo ""
echo "   rm -rf ~/.hermes"
echo "   rm -rf $(pwd)"
echo ""
echo "✨ Hermes 防禦網已成功解除安裝。感謝您的使用，後會有期！"
