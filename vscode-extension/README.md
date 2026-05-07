# FFBB Basketball MCP

VS Code extension that connects **GitHub Copilot agent mode** (and any MCP-compatible client) to the French Basketball Federation (FFBB) live data server.

## Features

- Registers the hosted FFBB MCP server in VS Code.
- Adds a command palette action: **FFBB MCP: Install Server**.
- Shows a one-time onboarding prompt to install the MCP server quickly.

Once installed, the following tools are available in agent mode:

| Tool | Description |
|------|-------------|
| `ffbb_search` | Search clubs, players, competitions |
| `ffbb_club` | Club info, teams, calendar, results |
| `ffbb_get` | Rankings, match details (poule, phase…) |
| `ffbb_next_match` | Next upcoming match for a team |
| `ffbb_last_result` | Last played match result |
| `ffbb_team_summary` | Full summary for a team |
| `ffbb_resolve_team` | Resolve ambiguous team references |

## Quick Install (no extension needed)

Click to add the remote MCP server directly to VS Code:

[Install FFBB Basketball MCP](vscode:mcp/install?%7B%22name%22%3A%22ffbb-mcp%22%2C%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fffbb.desimone.fr%2Fmcp%22%7D)

Or paste this in your `.vscode/mcp.json`:

```json
{
  "servers": {
    "ffbb-mcp": {
      "type": "http",
      "url": "https://ffbb.desimone.fr/mcp"
    }
  }
}
```

## Usage

1. Install this extension
2. Run **FFBB MCP: Install Server** from the command palette, or accept the one-time install prompt
3. Open GitHub Copilot Chat → switch to **Agent mode**
4. The FFBB tools are available

**Example prompts:**
- *"Quel est le prochain match du Stade Clermontois ?"*
- *"Montre-moi le classement de la Pro B"*
- *"Résultats du week-end pour Gerzat Basket"*

## Requirements

- VS Code ≥ 1.101
- GitHub Copilot (for agent mode)
- Internet access to `ffbb.desimone.fr`

## Links

- [GitHub Repository](https://github.com/nickdesi/FFBB-MCP-Server)
- [Documentation](https://github.com/nickdesi/FFBB-MCP-Server#readme)
- [Issues](https://github.com/nickdesi/FFBB-MCP-Server/issues)
