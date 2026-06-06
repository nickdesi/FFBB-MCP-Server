# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Paramètre `adversaire` dans `ffbb_club`** : Nouveau paramètre optionnel `adversaire` pour `action="calendrier"` permettant de filtrer uniquement les confrontations directes entre deux équipes. Insensible à la casse et aux accents, supporte les noms partiels (ex: `"Royat"` trouve `"ROYAT ORCINES CLUB BASKET BALL - 1"`). Voir `docs/TOOLS_REFERENCE.md` pour les exemples d'utilisation.

### Changed
- **Cache calendrier** : La clé de cache inclut maintenant le paramètre `adversaire` pour éviter les collisions.
- **Tests unitaires** : Mise à jour de `test_ffbb_club_auto_res.py` pour inclure le nouveau paramètre dans les assertions.

## [1.4.0] - 2026-06-02

### Performance
- **Connection pooling httpx** : limites configurées (`max_connections=50`, `max_keepalive_connections=20`) dans `app_factory.py` pour réduire la latence et éviter la saturation des descripteurs de fichiers.
- **Timeouts granulaires** : séparation `connect=5s / read=15s / write=10s / pool=30s` remplaçant les timeouts globaux pour un meilleur contrôle de la latence.
- **Suppression Redis** : suppression complète du backend Redis optionnel (code mort, dépendance inutilisée) ; le backend SQLite est le seul backend de cache HTTP supporté.
- **`prune_payload` optimisé** : skip rapide si `len <= limit` pour les appels MCP les plus fréquents.
- **Token refresh conditionnel** : évite les I/O réseau inutiles si le token est encore valide.
- **`lru_cache` eviction** : nettoyage proactif des caches LRU pour les phases éliminatoires (évite l'accumulation mémoire en saison).

### Changed
- **GitHub Actions modernisés** : épinglage SHA sur toutes les actions (`actions/checkout@v4`, `astral-sh/setup-uv@v5`, `docker/login-action`, etc.) ; matrix strategy Python 3.12/3.13 ; cache uv partagé entre jobs.
- **Workflow CI amélioré** : jobs parallèles (`lint`, `test`, `type-check`), concurrency groups avec cancel-in-progress, artefacts de couverture uploadés.
- **Workflow deploy** : health check post-déploiement avec retry ; notification de statut (succès/échec) dans le summary GitHub.
- **Workflow update-agents-md** : déclenchement sur push `src/**` uniquement.
- **`routes.py` nettoyé** : suppression des imports Redis, simplification du middleware CORS/Trusted Host.
- **`client.py` robuste** : retry exponentiel sur `get_client_async` ; gestion propre du cas où le token est encore frais.
- **`utils.py`** : ajout de `format_salle_info` helper pour la normalisation des adresses de salle.

### Fixed
- `common.py` : nettoyage de 150+ lignes de code Redis mort et de wrappers fantômes.
- Workflows : suppression de `redis` des services de test Docker Compose.
- AGENTS.md : mise à jour de l'architecture et des variables d'environnement (suppression des variables Redis).

## [1.3.1] - 2026-05-21

### Added
- **Correction robuste U7/U9** : Parsing plus souple des catégories de jeunes dans `utils.py` pour éviter des crashs ou faux positifs.
- **Suppression d'avertissements** : Correction de l'utilisation de `utcnow()` déprécié en Python.

### Changed
- **Modularisation de `services.py`** : Découpage du fichier monolithique en modules spécialisés sous `src/ffbb_mcp/services/` (`common.py`, `club.py`, `poule.py`, `salle.py`, `search.py`, `warmup.py`).
- **Robustesse & Résolution d'imports** : Importation dynamique des services et du client pour assurer la compatibilité avec la suite de tests et le mocking `pytest`.
- **Sécurisation des tâches en arrière-plan** : Maintien d'une référence forte (`_background_tasks` dans `routes.py`) pour la tâche asynchrone de `warm-up` afin d'éviter qu'elle soit collectée par le Garbage Collector (Règles RUF006).
- **Correctifs CI/CD** : Adaptation de `tools/update_agents_md.py` pour supporter la structure modulaire et analyser récursivement tout le dossier `services/` (calcul de lignes globaux, parsing des variables d'environnement comme `FFBB_POULE_FETCH_CONCURRENCY`, et arbre d'architecture complet dans `AGENTS.md`).

## [1.3.0] - 2026-05-20

### Added
- Ajout du dashboard (`/dashboard`), enrichissement de `/metrics.json` et `/health` avec statistiques d'utilisation du cache
- Rafraîchissement automatique des scores en direct le week-end

### Changed
- Refonte complète de l'infrastructure CI/CD (Ruff, actions épinglées par SHA, exécution concurrente)
- Nettoyage des métriques Prometheus et suppression du code mort et des dépendances inutilisées
- Amélioration de la robustesse des processus de validation et de la couverture

### Performance
- Optimisation majeure du cache (TTLCache/TLRUCache, résolution de l'inflation des clés)
- Optimisation des chemins critiques dans `services.py` et de la fonction `prune_payload` dans `utils.py`

## [1.2.0] - 2026-04-30

### Added
- Nouveau **Dashboard Live** (accessible via `/dashboard`) avec metrics temps réel et efficacité du cache.
- Design premium et responsive pour le dashboard, aligné sur la charte graphique du site.
- Bouton "Retour au site" sur le dashboard pour une navigation fluide.
- Lien vers le Dashboard direct sur la page d'accueil.

### Fixed
- Correction de la cohérence des versions entre le code, la documentation et le site web.

## [1.0.0] - 2026-04-21

### 🚀 Production Ready (V1.0)
We are extremely proud to announce the **V1.0.0 stable release** of the **FFBB MCP Server**.
This major milestone brings enterprise-grade stability, lightning-fast intelligent caching, and rigorous compliance with the latest Model Context Protocol (MCP) standards. 
Built specifically to empower Large Language Models (LLMs) with deep, contextual real-time data from the French Basketball Federation, this release gives absolute confidence for production workloads.

### Features
- **Intelligent Prompt Directives**: Complete rewrite of the `.prompts` system to provide strict, unambiguous LLM-routing directives. LLMs now automatically self-correct ambiguities via context indices, drastically reducing hallucinations.
- **Enterprise-Grade Caching Strategy**: Split processing and caching for Match/Poule contexts. Dynamic TTL assignments based on live match status ensure real-time accuracy without overwhelming external endpoints.
- **Dual-Transport Layer Architecture**: Fully verified stable support for both `stdio` and `SSE` (Server-Sent Events) MCP transports, adhering strictly to the spec `2025-11-25`.
- **Search Robustness**: Overhauled the Meilisearch integration to correctly handle edge-cases (like JAV - Jeanne d'Arc de Vichy) where local data indexing previously failed.
- **GEO/SEO Optimized Documentation**: Comprehensive optimization of the GitHub Pages documentation and repository README, ensuring maximum discoverability for autonomous agents and human users.

### Fixed
- Addressed multiple critical edge-cases related to incomplete data in regional tournaments.
- Fixed an issue where the application cache was improperly shared between `classement` and `poule` calculations.
- Cleaned up duplicate and legacy code, removing deprecated components for a hardened security model.

### Removed
- Removed legacy HTTP routes that bypassed the core MCP logic. All data should now securely flow directly through the standard MCP protocol.
