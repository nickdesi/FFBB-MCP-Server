# ==============================================================================
# FFBB MCP Server — Installateur Automatique 1-Clic pour Windows PowerShell
# ==============================================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "SilentlyContinue"

Write-Host ""
Write-Host "🏀 FFBB MCP Server — Installation Automatique 1-Clic" -ForegroundColor DarkYellow
Write-Host "Configuration automatique de vos assistants IA (Claude Desktop, Cursor, Antigravity)..." -ForegroundColor Cyan
Write-Host ""

# 1. Claude Desktop (%APPDATA%\Claude\claude_desktop_config.json)
$claudeDir = "$env:APPDATA\Claude"
$claudeFile = "$claudeDir\claude_desktop_config.json"

if (-not (Test-Path $claudeDir)) {
    New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null
}

$claudeConfig = @{}
if (Test-Path $claudeFile) {
    try {
        $raw = Get-Content $claudeFile -Raw -Encoding UTF8
        if ($raw) {
            $claudeConfig = $raw | ConvertFrom-Json -AsHashtable
        }
    } catch {}
}

if (-not $claudeConfig.ContainsKey("mcpServers")) {
    $claudeConfig["mcpServers"] = @{}
}

$claudeConfig["mcpServers"]["ffbb"] = @{
    command = "cmd"
    args = @("/c", "npx", "-y", "@modelcontextprotocol/client-sse", "https://ffbb.desimone.fr/mcp")
}

$claudeConfig | ConvertTo-Json -Depth 10 | Set-Content $claudeFile -Encoding UTF8
Write-Host "  [✓] Claude Desktop configuré avec succès ! ($claudeFile)" -ForegroundColor Green

# 2. Cursor IDE (%USERPROFILE%\.cursor\mcp.json)
$cursorDir = "$env:USERPROFILE\.cursor"
$cursorFile = "$cursorDir\mcp.json"

if (-not (Test-Path $cursorDir)) {
    New-Item -ItemType Directory -Path $cursorDir -Force | Out-Null
}

$cursorConfig = @{}
if (Test-Path $cursorFile) {
    try {
        $raw = Get-Content $cursorFile -Raw -Encoding UTF8
        if ($raw) {
            $cursorConfig = $raw | ConvertFrom-Json -AsHashtable
        }
    } catch {}
}

if (-not $cursorConfig.ContainsKey("mcpServers")) {
    $cursorConfig["mcpServers"] = @{}
}

$cursorConfig["mcpServers"]["ffbb"] = @{
    url = "https://ffbb.desimone.fr/mcp"
}

$cursorConfig | ConvertTo-Json -Depth 10 | Set-Content $cursorFile -Encoding UTF8
Write-Host "  [✓] Cursor / Windsurf configuré avec succès ! ($cursorFile)" -ForegroundColor Green

# 3. Google Antigravity
$agyDir = "$env:USERPROFILE\.gemini\antigravity-ide"
if (Test-Path "$env:USERPROFILE\.gemini") {
    if (-not (Test-Path $agyDir)) {
        New-Item -ItemType Directory -Path $agyDir -Force | Out-Null
    }
    $agyFile = "$agyDir\mcp_config.json"
    $agyConfig = @{}
    if (Test-Path $agyFile) {
        try {
            $raw = Get-Content $agyFile -Raw -Encoding UTF8
            if ($raw) {
                $agyConfig = $raw | ConvertFrom-Json -AsHashtable
            }
        } catch {}
    }
    if (-not $agyConfig.ContainsKey("mcpServers")) {
        $agyConfig["mcpServers"] = @{}
    }
    $agyConfig["mcpServers"]["ffbb"] = @{
        serverUrl = "https://ffbb.desimone.fr/mcp"
    }
    $agyConfig | ConvertTo-Json -Depth 10 | Set-Content $agyFile -Encoding UTF8
    Write-Host "  [✓] Google Antigravity configuré avec succès !" -ForegroundColor Green
}

Write-Host ""
Write-Host "🎉 Installation terminée avec succès !" -ForegroundColor Green
Write-Host "Redémarrez Claude Desktop ou Cursor pour profiter des outils Basket FFBB !" -ForegroundColor Cyan
Write-Host ""
