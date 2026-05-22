#!/bin/bash
# Hermes MCP Guard - 發布前自動化體檢腳本

echo "🔍 開始開源專案健檢..."
echo ""

# 1. 檢查隱私關鍵字
KEYWORDS=("范" "Ming-jie" "范銘傑" "43500" "永和" "安聯" "mortgage" "房貸" "基富通")

PASS=true
for word in "${KEYWORDS[@]}"; do
    if grep -rnE "$word" . --exclude-dir=.git --exclude=release_check.sh 2>/dev/null; then
        echo "❌ 警告：偵測到隱私敏感關鍵字 '$word'，請手動清理！"
        PASS=false
    fi
done

# 2. 檢查絕對路徑硬編碼
if grep -rn "/home/$(whoami)" . --exclude-dir=.git --exclude-dir=__pycache__ --exclude=release_check.sh 2>/dev/null; then
    echo "❌ 警告：偵測到本地硬編碼路徑，請改用相對路徑或環境變數！"
    PASS=false
fi

# 3. 檢查 README 存在
if [ ! -f "README.md" ]; then
    echo "❌ 錯誤：缺少 README.md"
    PASS=false
fi

# 4. 檢查 LICENSE 存在
if [ ! -f "LICENSE" ]; then
    echo "❌ 錯誤：缺少 LICENSE 檔案"
    PASS=false
fi

# 5. 檢查執行權限
if [ ! -x "hermes_guard.sh" ]; then
    echo "⚠️ 警告：hermes_guard.sh 未設置執行權限"
fi

# 6. 檢查 .gitignore 存在
if [ ! -f ".gitignore" ]; then
    echo "⚠️ 警告：缺少 .gitignore"
fi

echo ""
if $PASS; then
    echo "✅ 健檢完成！此專案已通過隱私與規範檢查，可以安全開源。"
    exit 0
else
    echo "❌ 健檢失敗，請修正上述問題後再發布。"
    exit 1
fi
