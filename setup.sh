#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Hermes MCP Guard — 一鍵安裝腳本
# 自動建立目錄、複製抗體庫、設定權限
# ═══════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 🦅 BUG-B fix: 統一使用 HERMES_HOME（與 hermes_guard.py 一致）
# 向後相容：如果使用者已設定舊的 HERMES_DIR，自動映射
HERMES_HOME="${HERMES_HOME:-${HERMES_DIR:-$HOME/.hermes}}"
GUARD_SH="$SCRIPT_DIR/hermes_guard.sh"
CORE_DIR="$SCRIPT_DIR/core"
PITFALLS_SRC="$CORE_DIR/pitfalls.json"
KG_SRC="$CORE_DIR/knowledge_graph.json"

echo "🛡️  Hermes MCP Guard — 安裝程式"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. 環境檢查 ──
echo "1/5 檢查環境..."

if ! command -v python3 &>/dev/null; then
    echo "   ❌ 未找到 python3，請先安裝 Python 3.10+"
    exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "   ✅ Python $PY_VER"

if ! command -v bash &>/dev/null; then
    echo "   ❌ 未找到 bash"
    exit 1
fi
echo "   ✅ bash"

# 檢查 mcp 套件
if ! python3 -c 'import mcp' 2>/dev/null; then
    echo "   ⚠️  mcp 套件未安裝，正在安裝..."
    python3 -m pip install --break-system-packages mcp 2>/dev/null || \
    python3 -m pip install mcp
fi
echo "   ✅ mcp 套件就緒"

# ── 2. 建立目錄結構 ──
echo "2/5 建立目錄..."
mkdir -p "$HERMES_HOME"
echo "   ✅ $HERMES_HOME"

# ── 3. 複製抗體庫 ──
echo "3/5 部署核心防禦抗體..."
# 🦅 BUG-C fix: pitfalls.json 需放在 self_evolution/ 子目錄（hermes_guard.py 讀取路徑）
mkdir -p "$HERMES_HOME/self_evolution"
if [ -f "$PITFALLS_SRC" ]; then
    cp "$PITFALLS_SRC" "$HERMES_HOME/self_evolution/pitfalls.json"
    echo "   ✅ pitfalls.json → $HERMES_HOME/self_evolution/"
fi

if [ -f "$KG_SRC" ]; then
    cp "$KG_SRC" "$HERMES_HOME/self_evolution/knowledge_graph.json"
    echo "   ✅ knowledge_graph.json → $HERMES_HOME/self_evolution/"
fi

# ── 4. 設定權限 ──
echo "4/5 設定權限..."
chmod +x "$GUARD_SH"
echo "   ✅ hermes_guard.sh 可執行"

# ── 5. 完成 ──
echo "5/5 安裝完成！"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  下一步："
echo ""
echo "  在 Claude Desktop 設定檔加入："
echo ""
echo '  {'
echo '    "mcpServers": {'
echo '      "hermes-guard": {'
echo "        \"command\": \"python3\","
echo "        \"args\": [\"$SCRIPT_DIR/hermes_mcp.py\"]"
echo '      }'
echo '    }'
echo '  }'
echo ""
echo "  ⚠️  Safety Notice: 此工具會在本機執行 shell 指令。"
echo "     請務必先審閱 hermes_guard.sh 的內容。"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
