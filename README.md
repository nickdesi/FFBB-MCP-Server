# FFBB MCP Server

Serveur **MCP (Model Context Protocol)** pour accéder aux données de la **Fédération Française de Basketball (FFBB)** depuis ton IA.

## Fonctionnalités

| Outil | Description |
|-------|-------------|
| `ffbb_get_lives` | Matchs en cours (scores live) |
| `ffbb_get_saisons` | Saisons disponibles |
| `ffbb_get_competition` | Détails d'une compétition par ID |
| `ffbb_get_poule` | Classement et matchs d'une poule |
| `ffbb_get_organisme` | Informations d'un club par ID |
| `ffbb_search_competitions` | Recherche de compétitions par nom |
| `ffbb_search_organismes` | Recherche de clubs par nom/ville |
| `ffbb_search_rencontres` | Recherche de matchs par nom |
| `ffbb_search_salles` | Recherche de salles par nom/ville |
| `ffbb_multi_search` | Recherche globale sur tous les types |

> **Aucune clé API requise** — les tokens sont récupérés automatiquement depuis l'API publique FFBB.

## Installation

```bash
# Créer un environnement virtuel
python -m venv .venv
source .venv/bin/activate

# Installer le serveur
pip install -e ".[dev]"
```

## Lancement

```bash
# Mode développement avec MCP Inspector
npx @modelcontextprotocol/inspector python -m ffbb_mcp

# Mode direct (stdio pour intégration MCP)
python -m ffbb_mcp
```

## Configuration dans Gemini CLI

Ajouter dans `~/.gemini/settings.json` :

```json
{
  "mcpServers": {
    "ffbb": {
      "command": "python",
      "args": ["-m", "ffbb_mcp"],
      "cwd": "/chemin/vers/FFBB MCP server"
    }
  }
}
```

## Configuration dans Claude Desktop

Ajouter dans `~/Library/Application Support/Claude/claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "ffbb": {
      "command": "/chemin/vers/.venv/bin/python",
      "args": ["-m", "ffbb_mcp"],
      "cwd": "/chemin/vers/FFBB MCP server"
    }
  }
}
```

## Tests

```bash
pytest tests/ -v
```

## Exemples de questions à poser à ton IA

- *"Quels matchs de basketball sont en cours en ce moment ?"*
- *"Cherche les clubs de basketball à Lyon"*
- *"Donne-moi le calendrier du championnat Nationale 1"*
- *"Où se joue le prochain match de l'ASVEL ?"*
- *"Quel est le classement de la poule A du championnat Pro B ?"*

## Source des données

Librairie [`ffbb-api-client-v2`](https://github.com/Rinzler78/FFBBApiClientV2_Python) — Apache 2.0
