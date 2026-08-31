#!/usr/bin/env bash
# ==============================================================================
# FFBB MCP Server — Installateur Automatique 1-Clic pour macOS & Linux
# ==============================================================================
set -e

GREEN="\033[0;32m"
ORANGE="\033[38;5;208m"
BLUE="\033[0;34m"
CYAN="\033[0;36m"
BOLD="\033[1m"
NC="\033[0m"

echo -e "\n${ORANGE}${BOLD}🏀 FFBB MCP Server — Installation Automatique 1-Clic${NC}"
echo -e "${CYAN}Configuration automatique de vos assistants IA (Claude Desktop, Cursor, Antigravity, VS Code)...${NC}\n"

PYTHON_BIN=$(command -v python3 || command -v python || true)
if [ -z "$PYTHON_BIN" ]; then
    echo -e "${ORANGE}⚠️ Python 3 n'a pas été détecté sur votre machine. Utilisation du mode basique.${NC}"
fi

# 1. Claude Desktop (macOS & Linux)
CLAUDE_CONFIG_DIR=""
if [ "$(uname)" == "Darwin" ]; then
    CLAUDE_CONFIG_DIR="$HOME/Library/Application Support/Claude"
else
    CLAUDE_CONFIG_DIR="$HOME/.config/Claude"
fi

CLAUDE_CONFIG_FILE="$CLAUDE_CONFIG_DIR/claude_desktop_config.json"

if [ -d "$CLAUDE_CONFIG_DIR" ] || [ -f "$CLAUDE_CONFIG_FILE" ]; then
    mkdir -p "$CLAUDE_CONFIG_DIR"
    $PYTHON_BIN -c "
import json, os
path = os.path.expanduser('$CLAUDE_CONFIG_FILE')
data = {}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {}
if 'mcpServers' not in data:
    data['mcpServers'] = {}
data['mcpServers']['ffbb'] = {
    'command': 'npx',
    'args': ['-y', '@modelcontextprotocol/client-sse', 'https://ffbb.desimone.fr/mcp']
}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print('ok')
" > /dev/null 2>&1 || true
    echo -e "  ${GREEN}✓ Claude Desktop configuré avec succès !${NC} ($CLAUDE_CONFIG_FILE)"
else
    # Si le dossier n'existe pas encore, on le pré-crée pour quand Claude Desktop sera installé
    mkdir -p "$CLAUDE_CONFIG_DIR"
    $PYTHON_BIN -c "
import json, os
path = os.path.expanduser('$CLAUDE_CONFIG_FILE')
data = {'mcpServers': {'ffbb': {'command': 'npx', 'args': ['-y', '@modelcontextprotocol/client-sse', 'https://ffbb.desimone.fr/mcp']}}}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
" > /dev/null 2>&1 || true
    echo -e "  ${GREEN}✓ Claude Desktop pré-configuré !${NC} ($CLAUDE_CONFIG_FILE)"
fi

# 2. Cursor IDE (~/.cursor/mcp.json)
CURSOR_DIR="$HOME/.cursor"
CURSOR_CONFIG_FILE="$CURSOR_DIR/mcp.json"
mkdir -p "$CURSOR_DIR"
$PYTHON_BIN -c "
import json, os
path = os.path.expanduser('$CURSOR_CONFIG_FILE')
data = {}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {}
if 'mcpServers' not in data:
    data['mcpServers'] = {}
data['mcpServers']['ffbb'] = {
    'url': 'https://ffbb.desimone.fr/mcp'
}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
" > /dev/null 2>&1 || true
echo -e "  ${GREEN}✓ Cursor / Windsurf configuré avec succès !${NC} ($CURSOR_CONFIG_FILE)"

# 3. Google Antigravity (~/.gemini/antigravity-ide/mcp_config.json)
AGY_DIR="$HOME/.gemini/antigravity-ide"
if [ -d "$HOME/.gemini" ]; then
    mkdir -p "$AGY_DIR"
    AGY_CONFIG_FILE="$AGY_DIR/mcp_config.json"
    $PYTHON_BIN -c "
import json, os
path = os.path.expanduser('$AGY_CONFIG_FILE')
data = {}
if os.path.exists(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {}
if 'mcpServers' not in data:
    data['mcpServers'] = {}
data['mcpServers']['ffbb'] = {
    'serverUrl': 'https://ffbb.desimone.fr/mcp'
}
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
" > /dev/null 2>&1 || true
    echo -e "  ${GREEN}✓ Google Antigravity configuré avec succès !${NC}"
fi

echo -e "\n${BOLD}${GREEN}🎉 Installation terminée avec succès !${NC}"
echo -e "${CYAN}Redémarrez votre client IA (Claude Desktop, Cursor...) pour commencer à poser vos questions sur le basket français !${NC}\n"
