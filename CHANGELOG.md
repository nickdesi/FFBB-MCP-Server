# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Gestion optimisée du démarrage de saison 2026-2027 (0 match disputé)** : Neutralisation des faux classements d'attaque/défense dans `analytics.py` et statut explicite en ouverture de saison.
- **Enrichissement des catégories & formats FFBB** : Support de `U7` (Baby Basket), `U9` (Mini Basket), `U20` (Juniors), `U21` (Espoirs), formats 3x3 (`Superleague`, `Juniorleague`, `Open Plus`, `Open Start`) et codes jeunes régionaux/départementaux (`RM18`, `RF18`, `DM15`, `DF13`, `RM20`, `DM20`).
- **Couverture intégrale des Ressources MCP (URI `ffbb://`)** : Enregistrement de `ffbb://rencontre/{id}`, `ffbb://salle/{id}`, `ffbb://officiel/{id}`, `ffbb://entraineur/{id}` et support étendu de `type="salle"` dans `ffbb_get`.
- **Résolution précise des clubs et ententes** : Boost de score 2.0 pour égalité exacte de nom de club et support de `force_refresh` sur l'ensemble de la chaîne de recherche.
- **Formatage standardisé de `result` (MCP)** : Sérialisation des listes d'objets de données en un tableau JSON unique `[...]` au lieu de blocs NDJSON sans crochets (`apply_fastmcp_json_formatting_patch`).
- **Support du paramètre `categorie` dans `ffbb_club`** : `categorie` est désormais accepté comme alias direct de `filtre`, permettant d'obtenir le classement complet en 1 étape fluide via `club_name` + `categorie`.

### Changed & Performance
- **Tri numérique natif des classements** : Normalisation et tri ascendant strict sur la position entière (`int(position)`), garantissant l'ordre `1, 2, ..., 10, 11...` au lieu de l'ordre lexicographique.
- **Épuration chirurgicale du payload `ffbb_team_summary`** : Suppression de la triple répétition de `club_resolu`, `team` et `_meta` dans `last_match` et `next_match` (gain de 40 à 50% de tokens).


## [1.10.0] - 2026-09-06

### Added
- **Résolution automatique des codes de division (seniors et jeunes)** :
  - Correspondance intelligente des divisions nationales (`NM1`, `NM2`, `NM3`, `NF1`, `NF2`, `NF3`), régionales (`PNM`, `PNF`, `PRM`, `PRF`, `R1`, `R2`, `R3`) et départementales (`DM1`, `DM2`, `DM3`, `DF1`, `DF2`, `DF3`).
  - Prise en charge des championnats jeunes (`NMU15`, `RMU15`, `DMU15`, `RFU18`, etc.) avec matching précis sur les codes et intitulés de compétitions.
  - Résolution directe vers l'équipe réelle engagée (ex: `NM3` -> `SEM1`, `PRM` -> `SEM2`, `RF2` -> `SEF2`, `NMU15` -> `U15M1`) sans confusion entre le chiffre de la division et le numéro d'équipe.
  - Filtrage automatique des rencontres amicales ou plateaux de pré-saison (`PLAT`, `AMICAL`) lorsqu'un championnat officiel existe.
- **Localisation directe d'un club dans une compétition multi-poules** :
  - Nouveau service `find_team_poule_service(competition_id, organisme_id_or_name)` avec fast-path ultra-rapide par inspection des engagements club et fallback multi-poules.
  - Nouveau paramètre `club` dans l'outil MCP `ffbb_get(type="competition", id=..., club="...")` retournant directement l'ID et le nom de la poule où évolue le club.
  - Auto-résolution du `poule_id` dans `ffbb_club(action="classement")` lorsqu'un filtre de division ou de niveau est fourni.
  - Tolérance pré-saison renforcée : inspection des `rencontres` quand les classements officiels sont encore vides avant la 1ère journée.

### Fixed
- **Désambiguïsation de clubs partagés** : utilisation du genre et de la catégorie demandée pour désambiguïser immédiatement les clubs homonymes (ex: sections féminine vs masculine).
- **Typage Pyright** : sécurisation de l'indexation de `equipes_bilan` dans `ffbb_team_summary`.

## [1.9.0] - 2026-09-05

### Added & Conformance
- **Contrainte JSON Schema `anyOf` (MCP Conformance)** : Déclaration formelle de `anyOf: [{"required": ["club_name"]}, {"required": ["organisme_id"]}]` sur 7 outils clés (`ffbb_resolve_team`, `ffbb_bilan`, `ffbb_team_summary`, `ffbb_bilan_saison`, `ffbb_last_result`, `ffbb_next_match`, `ffbb_club`). Élimine le round-trip réseau inutile où les agents IA tentaient un appel sans arguments.
- **Autorisation explicite des moteurs de recherche IA** : Intégration de `PerplexityBot`, `Perplexity-User`, `Google-Extended`, `GoogleOther`, `Claude-Web` et `ChatGPT-User` dans `_build_robots_txt()`, et blocage des scrapers d'entraînement brut (`Bytespider`, `CCBot`).

### Changed & Performance
- **Division par deux de l'empreinte de tokens initiale** :
  - Suppression totale de l'`outputSchema` généré par FastMCP sur tous les outils (-13,2k caractères / ~3 300 tokens économisés).
  - Épuration chirurgicale des docstrings et descriptions de paramètres sur `ffbb_club` (-64%) et `ffbb_bilan` (-88%).
  - Condensation dense (ZipAI) du `ROUTING_PROMPT` d'initialisation (-67% de caractères).
  - Réduction du payload global `tools/list` de 36 835 à 20 294 caractères (-45%).
- **Optimisation SEO / GEO** : Calibrage strict du titre (60 caractères) et de la meta description (157 caractères) pour un affichage SERP optimal à 100%.

## [1.8.0] - 2026-08-29

### Added
- **Outil MCP Face-à-Face & Comparaison (`ffbb_head_to_head`)** : Analyse comparative complète entre deux équipes (bilan historique direct de la saison, formes récentes respectives, duel statistique attaque vs défense, ratio domicile/extérieur et points clés narratifs d'avant-match).
- **Calculs de dynamique avancés** : Évaluation de la forme récente (`V-D-V-V...`), calcul précis des séries de victoires/défaites en cours et tendances de scoring.

### Changed & Performance
- **Optimisation du cycle de vie async & sérialisation** : Fermeture propre du client HTTP (`aclose`), sérialisation Pydantic accélérée et calculs de TTL dynamiques pilotés par l'état des rencontres.

### Fixed
- **Formulation des séries** : Correction du libellé des séries consécutives pour les occurrences `>= 2` uniquement.

## [1.7.0] - 2026-08-19

### Added
- **Endpoints GEO IA (`/llms.txt`, `/llms-full.txt`)** : Documentation standardisée des 12 outils FastMCP accessible directement par les moteurs de recherche IA (Perplexity, ChatGPT Search, Cursor, Copilot).
- **Index de documentation (`docs/README.md`)** : Sommaire interactif regroupant les références d'outils, guides d'architecture, benchmarks et règles métier.
- **Granularité des métriques de cache** : Catégorisation des causes de cache miss (`cold` / `expired` / `api_404`) dans `/metrics.json`.

### Changed & Performance
- **Optimisation des résolutions textuelles** : Fast-paths sur les acronymes de clubs (`resolve_acronym`), normalisation optimisée des numéros d'équipes (`format_team_name`) et accélération du calcul de distance de chaîne.
- **Landing page responsive** : Refonte de l'interface web `ffbb.desimone.fr` avec menu tiroir mobile, typographie fluide et élimination du CSS grid blowout.
- **Dépendances** : Mise à niveau vers `ffbb-data-client 2.3.4`.

### Fixed & Security
- **Sécurité (CVE-2026-69247)** : Mise à niveau de `cryptography` vers **50.0.0**.
- **Opérateur Directus** : Utilisation de l'opérateur `_eq` pour le filtre des saisons actives et retrait du champ `nom` dans `SaisonFields` pour prévenir les erreurs 403.
- **Monitoring (`/health`)** : Évaluation de la santé de l'instance basée sur le taux d'erreur en temps réel (`<= 5%`) plutôt que sur un compteur cumulatif d'erreurs historiques.

## [1.6.1] - 2026-08-01

### Security
- **`POST /cache/warmup` borné et authentifiable** : l'endpoint accepte désormais au plus `FFBB_WARMUP_MAX_ORGANISMES` organismes (défaut 50) et un body ≤ 64 Ko, avec validation stricte de `organisme_ids` (liste de chaînes non vides) — rejets `400`/`413`. Une clé optionnelle `FFBB_WARMUP_API_KEY` rend l'endpoint obligatoirement authentifié (`Authorization: Bearer <clé>`, rejet `401` sinon). Le service `warmup_cache_service` tronque également toute liste dépassant la borne en défense en profondeur. Adresse la DoS « Unauthenticated Unbounded Cache Warmup Resource Exhaustion » (CWE-400, GHSA-c5rm-rrrx-4mqq).

## [1.6.0] - 2026-07-25

### Added
- **Stale-While-Revalidate (SWR)** : les chemins chauds (`lives`, `saisons`, `poule`, `classement`) renvoient la valeur en cache immédiatement même si elle approche de l'expiration, et la rafraîchissent en arrière-plan. L'utilisateur ne subit jamais la latence (~400ms) d'un miss sur ces données. Réglable via `FFBB_SWR_ENABLED` et `FFBB_SWR_STALE_FRACTION`.
- **Cache persistant (SQLite) activé par défaut** : les caches service survivent aux redémarrages (critique en mode stdio où chaque session démarre dans un processus neuf) sans jamais servir de donnée périmée. Désactivable via `FFBB_SERVICE_CACHE_PERSIST=0`.
- **Warm-up au démarrage (mode HTTP)** : une boucle rafraîchit proactivement les `lives` pendant les fenêtres de match (`FFBB_LIVES_REFRESH_INTERVAL`), et un préchauffage optionnel charge les organismes/clubs configurés (`FFBB_WARMUP_ORGANISMES`).
- **Parallélisation du fan-out** : les workflows agrégés (`ffbb_bilan`, `get_calendrier_club_service`, `ffbb_equipes_club_service`) récupèrent les poules/classements en `asyncio.gather` — N appels indépendants coûtent un seul RTT au lieu de N×412ms.

### Changed
- `ffbb_get_classement_service` utilise désormais `_dedupe_inflight` (avec une map d'inflight dédiée `inflight_classement`) + SWR, conservant la même signature.
- `get_poule_service` calcule le TTL dynamique (`get_poule_ttl`) une seule fois et le sert de seuil de fraîcheur SWR.

### Fixed
- `reset_service_state` vide aussi le backing disque des caches persistants, garantissant l'isolation entre tests.

## [1.5.1] - 2026-06-07

### Fixed
- **CI/CD** : Correction de la matrix de tests GitHub Actions pour n'exécuter que Python 3.14 (alignement avec `requires-python >= 3.14`).
- **CI/CD** : Suppression de l'étape de vérification de santé du graphe obsolète.

## [1.5.0] - 2026-06-07

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
