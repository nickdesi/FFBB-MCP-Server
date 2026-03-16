# 🏀 FFBB MCP Server

<p align="center">
  <img src="./assets/logo.webp" width="250" alt="FFBB MCP Logo" />
  <br />
  <b>Le pont entre l'IA et le Basketball français.</b>
  <br />
  <i>Statistiques, calendriers, classements et lives officiels FFBB directement dans vos LLMs.</i>
  <br />
  <br />
  🌐 <b><a href="https://ffbb.desimone.fr">Visiter la Landing Page</a></b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python" alt="Python Version" />
  <img src="https://img.shields.io/badge/MCP-Latest-orange?style=for-the-badge" alt="MCP Version" />
  <a href="https://smithery.ai/server/ffbb-mcp-server"><img src="https://img.shields.io/badge/Smithery-Supported-yellow?style=for-the-badge&logo=codeigniter" alt="Smithery Badge" /></a>
  <a href="https://smithery.ai/servers/nickdesi/mcpffbb"><img src="https://smithery.ai/badge/nickdesi/mcpffbb" alt="Smithery Badge" /></a>
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License" />
</p>

---

## 🌟 Aperçu

Le serveur **FFBB MCP** est la **première et unique référence mondiale** pour exposer les données officielles du basketball français (FFBB) au protocole MCP. Il permet aux agents IA (comme Claude, Gemini, Cursor) de naviguer intelligemment dans l'écosystème du basket français : des ligues nationales aux championnats départementaux, avec une compréhension métier inégalée.

L'instance publique hébergée à https://ffbb.desimone.fr/mcp est l'instance canonique à utiliser ; les clients doivent pointer vers cette URL pour accéder aux données et outils fournis.

### 🏗️ Architecture

```mermaid
flowchart TD
  subgraph Clients ["Clients IA & IDEs"]
    direction TB
    A1["Google Antigravity"]
    A2["VS Code (MCP Extension)"]
    A3["Claude Desktop"]
    A4["Cursor / AnythingLLM"]
  end

  subgraph Hosted ["Hosted MCP Instance (https://ffbb.desimone.fr/mcp)"]
    direction TB
    B["Transport (SSE / HTTP)"]
    C["Core Logic (FastMCP)"]
    D["FFBB API Client"]
  end

  subgraph Remote ["Official FFBB API"]
    E["Official FFBB API"]
  end

  Clients -->|SSE / HTTP| Hosted
  Hosted <--> Remote
```

## 🌐 Connecter votre assistant IA (Clients)

L'instance publique du serveur FFBB MCP est accessible ici : https://ffbb.desimone.fr/mcp

Voici des exemples de configuration pour les clients et environnements courants — remplacez l'URL par `https://ffbb.desimone.fr/mcp` si elle n'est pas déjà renseignée.

### Claude Desktop
Ajoutez ou mettez à jour la configuration utilisateur pour pointer vers l'instance distante :

```json
{
  "mcpServers": {
    "ffbb": {
      "httpUrl": "https://ffbb.desimone.fr/mcp"
    }
  }
}
```

### Claude Code
Ajoutez le serveur distant via la CLI :

```bash
claude mcp add --transport http ffbb https://ffbb.desimone.fr/mcp
```

### Gemini CLI
Ajoutez l'URL dans `~/.gemini/settings.json` :

```json
{
  "mcpServers": {
    "ffbb": { "httpUrl": "https://ffbb.desimone.fr/mcp" }
  }
}
```

### Cursor / AnythingLLM / VS Code MCP Extension
Dans les clients qui supportent MCP via HTTP/SSE, ajoutez un nouveau serveur de type `streamable` (ou `http`) et renseignez l'URL : `https://ffbb.desimone.fr/mcp`.

### Smithery / intégrations (exemple)
Installer ou configurer un client qui se connecte à un MCP via l'URL publique :

```bash
npx -y @smithery/cli@latest install @nickdesi/mcpffbb --client claude --mcp-url https://ffbb.desimone.fr/mcp
```

### Remarques générales
- Transport recommandé : SSE (Streamable HTTP) — l'URL `https://ffbb.desimone.fr/mcp` expose le transport SSE.
- Health check : `/health` (GET) — utile pour vérifier la disponibilité depuis un UI de gestion ou un load balancer.
- Si un client signale une erreur CORS/Origins, vérifiez que l'UI locale (ex : `http://localhost:8000` de l'inspector) est autorisée par l'instance si tu testes depuis ton poste.

---

## 🛠️ Outils Disponibles

| Outil | Description | Paramètres Clés |
| ----- | ----------- | --------------- |
| `ffbb_search` | Recherche unifiée multi-critères. | `query`, `type` (competition, organisme, salle...), `limit` |
| `ffbb_get` | Accès direct par ID technique. | `id`, `type` (competition, poule, organisme) |
| `ffbb_club` | Actions groupées sur un club. | `action` (calendrier, equipes, classement), `club_name` ou `organisme_id` |
| `ffbb_lives` | Scores en direct (cache 30s). | Aucun |
| `ffbb_saisons` | Liste des saisons disponibles. | `active_only` |

> [!TIP]
> Pour une documentation exhaustive des schémas et des exemples d'appels, consultez la [Référence des Outils](docs/TOOLS_REFERENCE.md).

---

## 🎭 Prompts Prédéfinis (Intelligence Embarquée)

Le serveur expose des configurations prêtes à l'emploi pour transformer votre LLM en expert :

- `expert_basket` : **Le point d'entrée recommandé.** Configure l'agent avec toutes les règles de désambiguïsation (M/F, Équipe 1/2) et les workflows optimaux pour naviguer dans les données.
- `analyser_match` : Analyse approfondie d'une rencontre via son ID.
- `bilan_equipe` : Génère un rapport statistique complet sur la saison d'une équipe spécifique.
- `trouver_club`, `prochain_match`, `classement_poule` : Raccourcis pour des recherches ciblées.

---

## 🔧 Troubleshooting (FAQ)

- **Erreur 404 sur /mcp** : Assurez-vous d'utiliser `https` et non `http`.
- **Délai de réponse** : L'API FFBB peut parfois être lente, augmentez le timeout de votre client si possible.
- **WebSocket / SSE** : Sur Nginx Proxy Manager, activez impérativement **"Websockets Support"**.
- **Monitoring** : Si le serveur semble inactif, vous pouvez vérifier son état via l'endpoint de santé : `https://ffbb.desimone.fr/health`.

---

## ⚠️ Remarque sur l'accès

L'instance publique `https://ffbb.desimone.fr/mcp` est l'instance officielle à utiliser pour accéder aux données FFBB via MCP.
---

## 👨‍💻 Développement

Consultez le guide [CONTRIBUTING.md](CONTRIBUTING.md) pour installer l'environnement de développement et soumettre des PRs.

## 📄 Licence

Ce projet est sous licence [MIT](LICENSE).
