# Graph Report - .  (2026-05-14)

## Corpus Check
- 98 files · ~92,725 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 728 nodes · 1069 edges · 98 communities (39 shown, 59 thin omitted)
- Extraction: 78% EXTRACTED · 21% INFERRED · 0% AMBIGUOUS · INFERRED: 229 edges (avg confidence: 0.81)
- Token cost: 7,829 input · 1,287 output

## Community Hubs (Navigation)
- [[_COMMUNITY_FFBB Services Tests|FFBB Services Tests]]
- [[_COMMUNITY_Benchmark & Profiling Tools|Benchmark & Profiling Tools]]
- [[_COMMUNITY_FFBB Prompts Tests|FFBB Prompts Tests]]
- [[_COMMUNITY_Metrics & Dashboard Tests|Metrics & Dashboard Tests]]
- [[_COMMUNITY_Core Architecture Concepts|Core Architecture Concepts]]
- [[_COMMUNITY_Utils & Serialization Tests|Utils & Serialization Tests]]
- [[_COMMUNITY_Payload Pruning Tests|Payload Pruning Tests]]
- [[_COMMUNITY_Acronym Normalization Tests|Acronym Normalization Tests]]
- [[_COMMUNITY_Documentation Pages|Documentation Pages]]
- [[_COMMUNITY_Cache Config Tests|Cache Config Tests]]
- [[_COMMUNITY_Server Module Structure|Server Module Structure]]
- [[_COMMUNITY_Web Server & Dashboard Routes|Web Server & Dashboard Routes]]
- [[_COMMUNITY_Phase Resolution Tests|Phase Resolution Tests]]
- [[_COMMUNITY_Service Layer Core|Service Layer Core]]
- [[_COMMUNITY_Server Integration Tests|Server Integration Tests]]
- [[_COMMUNITY_Competition & Detail Services|Competition & Detail Services]]
- [[_COMMUNITY_Match & Date Services|Match & Date Services]]
- [[_COMMUNITY_MCP Resource Tests|MCP Resource Tests]]
- [[_COMMUNITY_Club Name Extraction Tests|Club Name Extraction Tests]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Shared Test Fixtures|Shared Test Fixtures]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 92|Community 92]]
- [[_COMMUNITY_Community 93|Community 93]]
- [[_COMMUNITY_Community 94|Community 94]]
- [[_COMMUNITY_Community 95|Community 95]]
- [[_COMMUNITY_Community 96|Community 96]]
- [[_COMMUNITY_Community 97|Community 97]]

## God Nodes (most connected - your core abstractions)
1. `_resolve_club_and_org()` - 19 edges
2. `ffbb_equipes_club_service()` - 17 edges
3. `FFBB MCP Server` - 17 edges
4. `TestPrompts` - 15 edges
5. `_search_generic()` - 15 edges
6. `serialize_model()` - 14 edges
7. `ffbb_get_classement_service()` - 13 edges
8. `ffbb_bilan_service()` - 13 edges
9. `get_calendrier_club_service()` - 13 edges
10. `ffbb_club()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `FFBB MCP Server Logo` --semantically_similar_to--> `Website Docs Logo`  [AMBIGUOUS] [semantically similar]
  assets/logo.webp → website-docs/public/logo.webp
- `FFBB MCP Server Logo` --semantically_similar_to--> `Website Logo`  [AMBIGUOUS] [semantically similar]
  assets/logo.webp → website/logo.webp
- `FFBB MCP Server Logo` --semantically_similar_to--> `VS Code Extension Icon`  [AMBIGUOUS] [semantically similar]
  assets/logo.webp → vscode-extension/assets/icon.png
- `test_returns_empty_when_no_poule()` --calls--> `ffbb_get_classement_service()`  [INFERRED]
  tests/test_services.py → src/ffbb_mcp/services.py
- `test_caches_empty_search_results()` --calls--> `search_organismes_service()`  [INFERRED]
  tests/test_services.py → src/ffbb_mcp/services.py

## Hyperedges (group relationships)
- **AI Agent Principles** — root_agents_push_tag_release_gate, root_agents_think_before_coding, root_agents_simplicity_first, root_agents_surgical_changes, root_agents_goal_driven_execution [EXTRACTED 1.00]
- **Caching & Performance System** — docs_performance_concurrency_limiter, docs_performance_inflight_dedup, docs_performance_ttl_cache, docs_performance_lazy_imports [EXTRACTED 1.00]
- **Transport Modes** — docs_architecture_streamable_http, docs_architecture_stdio [EXTRACTED 1.00]
- **MCP Request Lifecycle** — src_ffbb_mcp_server, src_ffbb_mcp_services, src_ffbb_mcp_client, src_ffbb_mcp__state, src_ffbb_mcp_metrics, src_ffbb_mcp_cache_strategy [INFERRED 0.85]
- **Phase Prioritization Test Suite** — tests_test_phase_prioritization, tests_test_feature_ranking_auto_resolve_poule, tests_test_ffbb_club_auto_res_club_resolution [INFERRED 0.75]
- **Version Sync Toolchain** — tests_test_version_tools_cross_tool, tools_check_version_alignment_checker, tools_sync_version_syncer [INFERRED 0.95]
- **Service Benchmark/Profiling Mock Pattern** — tools_measure_services_benchmark, tools_profile_services_profiler, tests_test_services_unit [INFERRED 0.85]
- **MCP Tool Ecosystem** — website_docs_reference_architecture, website_docs_reference_tools, website_docs_reference_rules, website_docs_guide_examples, ffbb_tool_suite [INFERRED 0.85]
- **Cache and Monitoring System** — cache_strategy, prometheus_monitoring, website_docs_reference_performance [INFERRED 0.85]
- **Production Deployment Stack** — ffbb_mcp_server, coolify_platform, streamable_http, website_docs_deploy_coolify [INFERRED 0.85]
- **VitePress Documentation Site Pages** — website_docs_assets_index_home_page, website_docs_assets_guide_introduction_intro, website_docs_assets_guide_installation_guide, website_docs_assets_guide_examples_workflows, website_docs_assets_deploy_coolify_deploy_guide, website_docs_assets_reference_architecture_arch, website_docs_assets_reference_performance_perf, website_docs_assets_reference_tools_tools, website_docs_assets_reference_rules_rules, website_docs_assets_chunks_framework_vue, website_docs_assets_chunks_theme_vitepress, website_docs_assets_chunks_search_box, website_docs_assets_chunks_search_index, website_docs_assets_app_vitepress_app [EXTRACTED 1.00]
- **FFBB MCP Tools Suite** — ffbb_search, ffbb_resolve_team, ffbb_club, ffbb_get, ffbb_next_match, ffbb_bilan, ffbb_bilan_saison, ffbb_team_summary [EXTRACTED 1.00]
- **FFBB MCP Infrastructure Stack** — ffbb_mcp_server, ffbb_api, ffbb_data_client, fastmcp, streamable_http, pydantic, cachetools_ttlcache, asyncio_semaphore, coolify, nginx_proxy_manager, prometheus, meilisearch, github_actions [EXTRACTED 1.00]
- **Guide section sidebar grouping — introduction, installation, examples** — guide_introduction_document, guide_installation_document, guide_examples_document [EXTRACTED 1.00]
- **Technical documentation sidebar — tools, architecture, performance, rules** — reference_tools_document, reference_architecture_document, reference_performance_document, reference_rules_document [EXTRACTED 1.00]
- **Architecture data flow: FastMCP → Service Layer → FFBB API** — reference_architecture_fastmcp, reference_architecture_service_layer, reference_architecture_ffbb_data_client [EXTRACTED 1.00]

## Communities (98 total, 59 thin omitted)

### Community 0 - "FFBB Services Tests"
Cohesion: 0.05
Nodes (56): ffbb_bilan_service(), ffbb_equipes_club_service(), ffbb_resolve_team_service(), get_calendrier_club_service(), multi_search_service(), Retourne les équipes engagées pour un club.      Paramètre `org_data` optionnel, Bilan complet d'une équipe toutes phases confondues en un seul appel.     Workfl, Récupère le calendrier et les résultats d'un club.      Workflow :     - Recherc (+48 more)

### Community 1 - "Benchmark & Profiling Tools"
Cohesion: 0.05
Nodes (48): _dedup_equipes_by_engagement(), _fetch_poule_matches(), _prioritize_phase(), Résout le club + filtre les équipes par catégorie/numéro.      Returns:, Charge les rencontres de toutes les poules en parallèle et filtre celles du club, Retourne uniquement les matchs de la phase la plus élevée., Centralise la résolution d'un club vers une liste d'organismes candidats.     Re, Déduplique les équipes par engagement_id pour éviter les doublons de matchs. (+40 more)

### Community 2 - "FFBB Prompts Tests"
Cohesion: 0.07
Nodes (28): analyser_match(), bilan_equipe(), calendrier_equipe(), classement_poule(), expert_basket(), prochain_match(), Définition des prompts MCP réutilisables pour le serveur FFBB., Active l'assistant expert en basketball français (prompt système complet). (+20 more)

### Community 3 - "Metrics & Dashboard Tests"
Cohesion: 0.06
Nodes (36): _build_dashboard_html(), Dashboard HTML pour le serveur FFBB MCP — route /dashboard., FFBB MCP Server — Fédération Française de Basketball., dec_inflight(), generate_prometheus_metrics(), get_snapshot(), inc_inflight(), _prom_block() (+28 more)

### Community 4 - "Core Architecture Concepts"
Cohesion: 0.06
Nodes (40): FastMCP Core Framework, ffbb-data-client, Pydantic Validation, HTTP Routes (health/metrics/dashboard/docs), Service Layer (services.py), Stdio Transport, Streamable HTTP Transport, Supported MCP Clients (+32 more)

### Community 5 - "Utils & Serialization Tests"
Cohesion: 0.09
Nodes (31): FFBBClientFactory, get_client_async(), _is_token_expired(), Helper shortcut for FFBBClientFactory.get_client_async()., Factory singleton pour le client FFBB avec token refresh proactif., ffbb_get_lives(), Matchs en cours (scores live, cache 30s). Retourne [] si aucun match., _enrich_matches_with_salle_details() (+23 more)

### Community 6 - "Payload Pruning Tests"
Cohesion: 0.08
Nodes (24): ffbb_club(), Outils agreges autour d'un club (calendrier, equipes, classement).      ✅ Outil, _CacheSupportsSetItem, get_asset_url_service(), Construit une URL d'asset Directus optimisée via le client V3., SupportsAssetUrl, is_match_day(), parse_categorie() (+16 more)

### Community 7 - "Acronym Normalization Tests"
Cohesion: 0.1
Nodes (19): enrich_acronym_cache(), _extract_initials(), _load_acronyms_cache(), _normalize_apostrophes(), normalize_query(), Gestion des alias et acronymes de clubs FFBB.  Ce module fournit : - Un dictionn, Charge le cache d'acronymes depuis le fichier JSON.      Si le fichier n'existe, Sauvegarde le cache d'acronymes dans le fichier JSON. (+11 more)

### Community 8 - "Documentation Pages"
Cohesion: 0.13
Nodes (26): Intelligent Cache Strategy, Coolify Platform, FastMCP Framework (mcp.server.fastmcp), FastMCP Framework, FFBB Official API, ffbb-data-client, FFBB MCP Server, FFBB MCP 12-Tool Suite (+18 more)

### Community 9 - "Cache Config Tests"
Cohesion: 0.13
Nodes (18): get_poule_ttl(), get_static_ttl(), is_in_match_window(), is_post_match_cooling(), Lendemain ou soirée après fermeture de fenêtre live., get_cache_ttls(), Retourne les TTL (en secondes) pour chaque cache service-level.      Cette fonct, _ttu_bilan() (+10 more)

### Community 10 - "Server Module Structure"
Cohesion: 0.12
Nodes (21): aliases.py — Club alias/acronym resolution, app_factory.py — Starlette app factory, cache_strategy.py — TTL strategy, Caching System concept, client.py — FFBB client factory, Club Alias Resolution concept, dashboard.py — HTML dashboard, __main__.py — Entry point (+13 more)

### Community 11 - "Web Server & Dashboard Routes"
Cohesion: 0.12
Nodes (14): Entry point for the FFBB MCP server., _build_index_html(), favicon(), ffbb_last_result(), _find_website_dir(), index(), logo(), _logo_response() (+6 more)

### Community 12 - "Phase Resolution Tests"
Cohesion: 0.12
Nodes (18): Résout le poule_id d'une équipe pour une phase donnée (ex: 'phase 3').      Si p, resolve_poule_id_service(), Vérifie que la résolution par phase fonctionne (Phase 2)., Vérifie que sans phase, on prend la phase au niveau le plus haut., Vérifie que l'équipe cible est bien marquée via is_target., test_ffbb_get_classement_service_highlighting(), test_resolve_poule_id_service_by_phase(), test_resolve_poule_id_service_default_to_latest() (+10 more)

### Community 13 - "Service Layer Core"
Cohesion: 0.2
Nodes (17): _cache_get(), _notify_cache_hit(), _notify_cache_miss(), Wrapper centralisé pour lire un cache avec metrics hit/miss.      Ce helper évit, search_communes_service(), search_competitions_service(), search_engagements_service(), search_entraineurs_service() (+9 more)

### Community 14 - "Server Integration Tests"
Cohesion: 0.14
Nodes (15): main(), Résout un niveau de log à partir d'une valeur d'environnement., Mappe le niveau Python vers un niveau uvicorn compatible., _resolve_log_level(), _resolve_uvicorn_log_level(), Tests d'intégration pour le serveur MCP FFBB refactoré., Vérifie que FastMCP est bien initialisé., Vérifie que les outils sont bien enregistrés via FastMCP. (+7 more)

### Community 15 - "Competition & Detail Services"
Cohesion: 0.17
Nodes (16): ffbb_get(), Recupere une ressource FFBB par identifiant.      - `type="competition"` equivau, _coerce_numeric_id(), _dedupe_inflight(), _dedupe_inflight_detail(), get_competition_service(), _get_inflight_lock(), get_organisme_service() (+8 more)

### Community 16 - "Match & Date Services"
Cohesion: 0.15
Nodes (14): ffbb_next_match(), ffbb_team_summary(), Résumé complet et agent-friendly pour une équipe.      Combine en UN seul appel, Prochain match à jouer pour une équipe précise.      ⚠️ SINGULIER UNIQUEMENT. Si, _extract_phase_num(), ffbb_last_result_service(), ffbb_next_match_service(), _freshness_meta() (+6 more)

### Community 17 - "MCP Resource Tests"
Cohesion: 0.18
Nodes (6): Définition des Resources MCP (Endpoints URI)., Enregistre les ressources sur l'instance FastMCP., register_resources(), DummyMCP, Tests des resources MCP FFBB., registered_resources()

### Community 18 - "Club Name Extraction Tests"
Cohesion: 0.27
Nodes (4): _extract_club_key_word(), Extrait le mot distinctif d'un nom de club en supprimant les termes génériques., Tests unitaires pour l'extraction du mot distinctif d'un club., TestExtractClubKeyWord

### Community 19 - "Community 19"
Cohesion: 0.18
Nodes (11): _build_robots_txt(), _build_sitemap_xml(), _get_logo_url(), _get_public_base_url(), health(), Endpoint de santé enrichi — lisible par machine et humain., robots_txt(), sitemap_xml() (+3 more)

### Community 20 - "Shared Test Fixtures"
Cohesion: 0.18
Nodes (10): mock_client(), mock_ctx(), patch_get_client(), Fixtures partagées pour les tests du serveur MCP FFBB., Client FFBB mocké pour les tests unitaires., Patch get_client_async pour qu'il retourne le mock_client par défaut., Contexte MCP mocké pour les tests unitaires., Services Unit Tests (+2 more)

### Community 21 - "Community 21"
Cohesion: 0.2
Nodes (10): ffbb_bilan(), ffbb_bilan_saison(), ffbb_get_saisons(), ffbb_resolve_team(), Bilan détaillé de la saison pour une équipe précise (toutes phases).      Cet ou, Bilan complet d'une équipe toutes phases confondues en UN seul appel.      ⚡ C'e, Liste des saisons FFBB. active_only=True pour la saison en cours uniquement., Identifie une equipe unique (Pivot central).      DOIT etre utilise avant `ffbb_ (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.27
Nodes (5): create_app(), app(), test_lifespan_runs_mcp_session_manager(), test_request_id_middleware_logs_client_disconnect(), test_request_id_middleware_returns_json_error()

### Community 23 - "Community 23"
Cohesion: 0.42
Nodes (8): get_client_version(), get_current_version(), main(), sync_lockfile(), update_changelog(), update_docs(), update_readme(), update_website()

### Community 24 - "Community 24"
Cohesion: 0.25
Nodes (8): Enregistre un appel API FFBB (latence + statut)., record_call(), _cache_set(), ffbb_get_classement_service(), _is_retriable_error(), Exécute un appel API avec logging, error handling et retry/backoff.      `coro`, Détermine si une erreur est réessayable., _safe_call()

### Community 25 - "Community 25"
Cohesion: 0.39
Nodes (3): format_poule_response(), Formate les données brutes d'une poule pour la réponse MCP.      Enrichit classe, TestFormatPouleResponse

### Community 26 - "Community 26"
Cohesion: 0.52
Nodes (6): _check_contains(), _check_tag(), main(), _project_version(), Check project version consistency across metadata and public docs., _read()

### Community 27 - "Community 27"
Cohesion: 0.33
Nodes (6): ffbb_version(), Retourne la version installée d'un package Python (stdlib-only)., Informations de version et configuration runtime du serveur FFBB MCP.      Retou, _sdk_version(), Vérifie le contrat de sortie de ffbb_version (dont cache_ttls)., test_ffbb_version_contract()

### Community 28 - "Community 28"
Cohesion: 0.33
Nodes (6): ffbb_search(), Validates a Meilisearch filter expression from user input.      Raises ValueErro, Recherche FFBB — clubs, compétitions, matchs, salles, tournois, etc.      type=', _validate_filter_by(), ffbb_search_service(), Service de recherche FFBB.      Recherche dans les données FFBB en fonction de p

### Community 29 - "Community 29"
Cohesion: 0.4
Nodes (4): Test symbolique pour valider que la logique de filtrage 'joue' est intentionnell, Vérifie la conservation du camelCase dans les réponses sérialisées.     Ce test, test_api_response_casing(), test_joue_logic_documentation()

### Community 30 - "Community 30"
Cohesion: 0.4
Nodes (5): Cache TTL Configuration Tests, Prompt Construction Tests, Server Integration Tests, VS Code Extension README, VS Code Extension Implementation

### Community 31 - "Community 31"
Cohesion: 0.5
Nodes (4): FFBB MCP Server Logo, VS Code Extension Icon, Website Docs Logo, Website Logo

### Community 32 - "Community 32"
Cohesion: 0.5
Nodes (4): _match_team_name(), _normalize_name(), Normalise un nom (strip, upper, supprime les accents sans perdre de caractères)., Retourne True si nom_equipe_rencontre correspond a l'equipe du club.      Regles

### Community 33 - "Community 33"
Cohesion: 0.5
Nodes (4): _extract_and_accumulate_bilan(), ffbb_saison_bilan_service(), _new_bilan_totals(), Service interne pour ffbb_bilan_saison.      Agrège le bilan de TOUTES les phase

### Community 34 - "Community 34"
Cohesion: 0.5
Nodes (4): Cache Optimization (TTLCache/TLRUCache), Dashboard Live, Version 1.2.0, Version 1.2.1

### Community 37 - "Community 37"
Cohesion: 0.67
Nodes (3): Resolve Poule & Ranking Tests, ffbb_club Auto-Resolution Tests, Phase Prioritization Tests

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (3): Version Tools Cross-Consistency Test, Version Alignment Checker, Version Synchronizer

## Ambiguous Edges - Review These
- `FFBB MCP Server Logo` → `Website Docs Logo`  [AMBIGUOUS]
  website-docs/public/logo.webp · relation: semantically_similar_to
- `FFBB MCP Server Logo` → `Website Logo`  [AMBIGUOUS]
  website/logo.webp · relation: semantically_similar_to
- `FFBB MCP Server Logo` → `VS Code Extension Icon`  [AMBIGUOUS]
  vscode-extension/assets/icon.png · relation: semantically_similar_to

## Knowledge Gaps
- **227 isolated node(s):** `Check project version consistency across metadata and public docs.`, `Tests des resources MCP FFBB.`, `Vérifie que _normalize_apostrophes remplace toutes les variantes.`, `Vérifie que normalize_query normalise les apostrophes avant la recherche.`, `Vérifie le fonctionnement de l'élagage chirurgical ZipAI.` (+222 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **59 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `FFBB MCP Server Logo` and `Website Docs Logo`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **What is the exact relationship between `FFBB MCP Server Logo` and `Website Logo`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **What is the exact relationship between `FFBB MCP Server Logo` and `VS Code Extension Icon`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `ffbb_club()` connect `Payload Pruning Tests` to `FFBB Services Tests`, `Web Server & Dashboard Routes`, `Phase Resolution Tests`, `Service Layer Core`, `Community 21`, `Community 24`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `_resolve_club_and_org()` connect `Benchmark & Profiling Tools` to `FFBB Services Tests`, `Community 32`, `Payload Pruning Tests`, `Acronym Normalization Tests`, `Service Layer Core`, `Competition & Detail Services`, `Club Name Extraction Tests`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Why does `FFBB MCP Server` connect `Documentation Pages` to `Server Integration Tests`, `Payload Pruning Tests`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `_resolve_club_and_org()` (e.g. with `test_resolve_club_and_org_logs_organisme_load_error()` and `test_resolve_club_and_org_logs_first_org_detail_error()`) actually correct?**
  _`_resolve_club_and_org()` has 11 INFERRED edges - model-reasoned connections that need verification._