# 📚 Documentation Technique — FFBB MCP Server

Bienvenue dans le centre de documentation officiel du serveur **FFBB MCP**.

---

## 🗂️ Sommaire des guides

| Document | Description | Public |
| :--- | :--- | :--- |
| **[🛠️ Référence des 12 Outils MCP](TOOLS_REFERENCE.md)** | Schémas complets des 12 outils FastMCP, paramètres d'entrée, retours JSON et exemples d'appels. | Développeurs & Agents IA |
| **[🏗️ Architecture Technique](ARCHITECTURE.md)** | Fonctionnement interne du serveur, FastMCP, transport Streamable HTTP, services et cycle de vie. | Développeurs & Architectes |
| **[💬 Exemples & Cas d'usage](EXAMPLES.md)** | Prompts types, exemples d'appels pour Claude Desktop, Cursor et assistants IA. | Utilisateurs & Intégrateurs |
| **[⚡ Performance & Optimisations](PERFORMANCE.md)** | Gestion du cache SQLite / SWR, benchmarks de latence, métriques Prometheus et dashboards. | Développeurs & DevOps |
| **[🐳 Guide de Déploiement Coolify](COOLIFY_DEPLOYMENT.md)** | Guide pas à pas pour déployer sur Coolify avec Nginx Proxy Manager et SSL. | DevOps & Administrateurs |
| **[📜 Règles Métier Basket (rules_ffbb.md)](rules_ffbb.md)** | Guide de navigation et heuristiques pour explorer les données FFBB (clubs, poules, classements, lives). | Développeurs & LLMs |

---

## 🚀 Accès Rapide aux Endpoints & Services

- **Site officiel & Landing Page** : [https://ffbb.desimone.fr/](https://ffbb.desimone.fr/)
- **Endpoint MCP Public (Streamable HTTP)** : `https://ffbb.desimone.fr/mcp`
- **Dashboard de Supervision** : [https://ffbb.desimone.fr/dashboard](https://ffbb.desimone.fr/dashboard)
- **Métriques Prometheus** : [https://ffbb.desimone.fr/metrics](https://ffbb.desimone.fr/metrics)
- **Health Check** : [https://ffbb.desimone.fr/health](https://ffbb.desimone.fr/health)
- **Découverte LLMs (GEO)** : [https://ffbb.desimone.fr/llms.txt](https://ffbb.desimone.fr/llms.txt)
- **Package Client sous-jacent** : [https://nickdesi.github.io/ffbb-data-client/](https://nickdesi.github.io/ffbb-data-client/)
