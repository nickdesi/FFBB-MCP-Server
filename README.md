# 🏀 FFBB MCP Server

<p align="center">
  <img src="./assets/logo.webp" width="180" alt="Logo FFBB MCP" style="border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.1);" />
</p>

<h3 align="center">Le basket français officiel, directement dans vos assistants IA.</h3>

<p align="center">
  Serveur <a href="https://modelcontextprotocol.io">MCP</a> pour consulter calendriers, classements, bilans, résultats et scores live de la FFBB.
  <br /><br />
  🌐 <b><a href="https://ffbb.desimone.fr">Site</a></b>
  · 🧩 <b><a href="https://github.com/nickdesi/FFBB-MCP-Server/releases/latest">Extension VS Code</a></b>
  · 📚 <b><a href="https://ffbb.desimone.fr/docs/">Documentation</a></b>
  · 💬 <b><a href="SUPPORT.md">Support</a></b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14%2B-blue?style=for-the-badge&logo=python" alt="Version Python" />
  <img src="https://img.shields.io/badge/version-1.5.1-green?style=for-the-badge" alt="Version" />
  <a href="https://smithery.ai/servers/nickdesi/mcpffbb"><img src="https://smithery.ai/badge/nickdesi/mcpffbb" alt="Badge Smithery" /></a>
  <img src="https://img.shields.io/github/actions/workflow/status/nickdesi/FFBB-MCP-Server/ci.yml?label=CI&style=for-the-badge" alt="Statut CI" />
  <img src="https://img.shields.io/badge/License-Apache--2.0-blue?style=for-the-badge" alt="Licence" />
</p>

---

## ⚡ Démarrage express

> [!TIP]
> Aucune installation requise : le serveur est **hébergé publiquement**. Ajoutez simplement l'endpoint à votre client MCP.

```text
https://ffbb.desimone.fr/mcp
```

Puis posez vos questions en langage naturel :

> _« Quel est le prochain match des U15 de mon club ? »_
> _« Donne-moi le classement de la poule et le dernier résultat. »_
> _« Y a-t-il des matchs en direct ce soir ? »_

👉 Voir la section [Installation](#-installation) pour votre client (VS Code, Claude, Cursor…).

---

## 📑 Sommaire

- [✨ Fonctionnalités](#-fonctionnalités)
- [🚀 Installation](#-installation)
  - [VS Code / GitHub Copilot](#vs-code--github-copilot)
  - [Claude Desktop](#claude-desktop)
  - [Cursor / autres clients MCP](#cursor--autres-clients-mcp)
  - [Google Antigravity](#google-antigravity)
- [🧰 Outils principaux](#-outils-principaux)
- [🌐 Instance publique](#-instance-publique)
- [🏗️ Architecture](#️-architecture)
- [💻 Développement local](#-développement-local)
- [📚 Documentation](#-documentation)
- [🤝 Communauté](#-communauté)

---

## ✨ Fonctionnalités

- 🗓️ **Calendriers & résultats** — matchs passés et à venir, par club ou par équipe.
- 🏆 **Classements** — poules complètes avec points, différentiel et forme.
- 📊 **Bilans agrégés** — toutes phases confondues en un seul appel.
- 🔴 **Scores live** — matchs en cours, mis à jour toutes les 30 s.
- 🔎 **Recherche universelle** — clubs, compétitions, salles, engagements.
- 🚀 **Optimisé pour les LLM** — réponses agrégées et cache TTL pour réduire le contexte et le nombre d'appels.

---

## 🚀 Installation

### VS Code / GitHub Copilot

**Option recommandée** — installer l'extension **FFBB Basketball MCP** depuis les [releases](https://github.com/nickdesi/FFBB-MCP-Server/releases/latest), puis ouvrir Copilot Chat en mode agent.

**Alternative sans extension** — [➕ Installer FFBB MCP en un clic](vscode:mcp/install?%7B%22name%22%3A%22ffbb-mcp%22%2C%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fffbb.desimone.fr%2Fmcp%22%7D)

### Claude Desktop

<details>
<summary><b>Option A — Via l'interface de Claude</b> (recommandé, sans prérequis)</summary>

<br />

Les versions récentes de Claude permettent d'ajouter des connecteurs directement depuis l'interface graphique :

1. Ouvrez les **Paramètres** de Claude, puis **Connecteurs** (ou **Plugins**).
2. Cliquez sur **Ajouter un connecteur personnalisé**.
3. Renseignez l'URL publique `https://ffbb.desimone.fr/mcp` et validez.

</details>

<details>
<summary><b>Option B — Via <code>claude_desktop_config.json</code></b> (nécessite Node.js)</summary>

<br />

Claude Desktop n'accepte que le transport `stdio` local : on utilise donc le bridge SSE officiel via `npx`.

> [!WARNING]
> **Prérequis : Node.js** (inclut `npm` et `npx`). Sans Node.js, privilégiez l'**Option A**.

```json
{
  "mcpServers": {
    "ffbb": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/client-sse",
        "https://ffbb.desimone.fr/mcp"
      ]
    }
  }
}
```

</details>

### Cursor / autres clients MCP

Configurez un serveur MCP distant :

| Champ | Valeur |
| --- | --- |
| Type | `Streamable HTTP` |
| URL | `https://ffbb.desimone.fr/mcp` |

### Google Antigravity

> [!WARNING]
> Un bug connu du client Go d'Antigravity (timeouts d'initialisation trop courts, gestion SSE sur serveur distant) peut provoquer des erreurs `context deadline exceeded` en `type: "http"`. Utilisez plutôt le proxy local `mcp-remote` (installé à la volée via `npx`) :

```json
"ffbb": {
  "command": "npx",
  "args": [
    "-y",
    "mcp-remote",
    "https://ffbb.desimone.fr/mcp"
  ]
}
```

---

## 🧰 Outils principaux

| Outil | Usage |
| --- | --- |
| `ffbb_bilan` | Bilan complet d'une équipe, toutes phases confondues. |
| `ffbb_team_summary` | Résumé agent : bilan, classement courant, dernier résultat, prochain match. |
| `ffbb_bilan_saison` | Bilan détaillé d'une équipe précise avec `numero_equipe`. |
| `ffbb_last_result` | Dernier match joué. |
| `ffbb_next_match` | Prochain match. |
| `ffbb_club` | Calendrier complet, équipes ou classement d'un club. |
| `ffbb_search` | Recherche clubs, compétitions, salles, matchs, engagements. |
| `ffbb_get` | Accès technique à une ressource FFBB par identifiant. |
| `ffbb_lives` | Matchs en direct. |
| `ffbb_saisons` | Saisons disponibles. |
| `ffbb_version` | Version et diagnostic runtime. |

> [!NOTE]
> Référence complète des paramètres : [`docs/TOOLS_REFERENCE.md`](docs/TOOLS_REFERENCE.md).

---

## 🌐 Instance publique

Endpoint MCP (transport **Streamable HTTP**) :

```text
https://ffbb.desimone.fr/mcp
```

| Endpoint | URL |
| --- | --- |
| 📊 Dashboard | `https://ffbb.desimone.fr/dashboard` |
| 📈 Métriques | `https://ffbb.desimone.fr/metrics.json` |
| ❤️ Santé | `https://ffbb.desimone.fr/health` |

---

## 🏗️ Architecture

```mermaid
flowchart LR
    A[Client MCP] -->|Streamable HTTP| B[FFBB MCP Server]
    B --> C[Services métier + cache]
    C --> D[ffbb-data-client]
    D --> E[API officielle FFBB]
```

Points clés :

- serveur Python 3.14+ basé sur `mcp[cli]`, `starlette` et `uvicorn` ;
- agrégation métier pour limiter le nombre d'appels et réduire le contexte LLM ;
- cache TTL adapté aux données live, calendriers et classements ;
- dashboard, métriques JSON et healthcheck intégrés.

Détails : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) et [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

---

## 💻 Développement local

```bash
uv sync --extra dev       # installer les dépendances
uv run ruff format .      # formater
uv run ruff check --fix . # linter
uv run mypy src           # vérifier les types
uv run pytest             # lancer les tests
```

Voir [`CONTRIBUTING.md`](CONTRIBUTING.md) pour les règles de contribution.

---

## 📚 Documentation

- [Exemples d’usage](docs/EXAMPLES.md)
- [Référence des outils](docs/TOOLS_REFERENCE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Performance et cache](docs/PERFORMANCE.md)
- [Déploiement Coolify](docs/COOLIFY_DEPLOYMENT.md)

---

## 🤝 Communauté

- [Contribuer](CONTRIBUTING.md)
- [Code de conduite](CODE_OF_CONDUCT.md)
- [Support](SUPPORT.md)
- [Sécurité](SECURITY.md)

---

<p align="center">
  <i>Projet non officiel, non affilié à la Fédération Française de BasketBall.</i>
</p>
