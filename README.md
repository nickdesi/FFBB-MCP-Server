# FFBB MCP Server

Serveur **MCP (Model Context Protocol)** pour accéder aux données de la **Fédération Française de Basketball (FFBB)** depuis ton IA.

## Fonctionnalités

| Outil | Description |
| :--- | :--- |
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

## Bonnes pratiques et Astuces pour les Agents IA

Pour optimiser l'utilisation de ce serveur MCP avec un LLM (Claude, Gemini, ChatGPT...), voici les stratégies recommandées :

### 1. Stratégie de Recherche

L'API de recherche (`ffbb_search_rencontres`) peut être capricieuse sur les noms courts ou les acronymes.
**Recommandation :** Privilégiez toujours le chemin "Organisme -> Engagements" pour une fiabilité à 100%.

1. `ffbb_search_organismes(name="...")` pour trouver l'ID du club.
2. `ffbb_get_organisme(id=...)` pour lister toutes les équipes et compétitions.
3. `ffbb_get_poule(id=...)` pour avoir le calendrier précis.

### 2. Filtrage Intelligent

Les clubs ont souvent plusieurs équipes dans la même catégorie (ex: U11M 1, U11M 2).

- Utilisez les indices de la requête (Genre, Catégorie, Numéro d'équipe) pour filtrer les résultats **avant** de faire des appels API supplémentaires.
- Si vous cherchez l'équipe 1, ignorez les poules où évolue l'équipe 2.

### 3. Gestion des Alias

Les clubs sont souvent connus par des sigles (ex: "SCBA" pour Stade Clermontois, "JAV" pour Vichy).

- Si une recherche exacte échoue, tentez l'acronyme ou le nom complet.
- Ce serveur expose les noms officiels, donc "Stade Clermontois" peut être listé sous "STADE CLERMONTOIS BASKET AUVERGNE".
