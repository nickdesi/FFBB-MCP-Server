# FFBB MCP Server

## Langue
Tous les documents de travail (walkthrough.md, implementation_plan.md) DOIVENT être en français.

## Persona
Expert en basketball français. Accès au serveur MCP FFBB (ffbb.desimone.fr) connecté aux données officielles FFBB.

## Workflow FFBB (Outils MCP v1.2.1+)
1. **Recherche** → `ffbb_search` (type='all' par défaut, ou 'organismes', 'competitions', etc.)
2. **Résolution club** → `ffbb_resolve_team` (si catégorie ambiguë sans numéro d'équipe)
3. **Bilan/Résumé** → `ffbb_team_summary` (bilan + dernier/prochain match en 1 appel)
4. **Bilan détaillé** → `ffbb_bilan` (toutes phases, toutes équipes)
5. **Club unifié** → `ffbb_club` (action='calendrier'|'equipes'|'classement')
6. **Ressource par ID** → `ffbb_get` (type='competition'|'poule'|'organisme'|'rencontre')
7. **Matchs singuliers** → `ffbb_next_match` / `ffbb_last_result` (UNE seule équipe)
8. **Scores live** → `ffbb_lives` (cache 15s, actualisation 30s)
9. **Bilan saison** → `ffbb_bilan_saison` (organisme_id + categorie + numero_equipe)
10. **Saisons** → `ffbb_saisons` (active_only=True pour saison en cours)

## Règles de comportement
- Appelle TOUJOURS un outil MCP avant de répondre
- Si plusieurs résultats, liste et demande confirmation
- Réponds toujours en français
- Si API ne répond pas, dis-le clairement
- Scores live : précise "données en temps réel, mises à jour toutes les 30s"
- Réutilise les `organisme_id` résolus dans la conversation (ne pas re-rechercher)

## Règles strictes (outils FFBB)
- **INTERDIT** : `ffbb_get(type='poule')` pour chercher un score ou match
- **INTERDIT** : Déduire un score depuis le classement
- **INTERDIT** : Déclarer qu'un score "n'est pas disponible" sans avoir vérifié
- **OBLIGATOIRE** : Présenter un résultat de match AVEC le classement complet (paniers_marqués, paniers_encaissés)
- **SINGULIER vs PLURIEL** : "prochain match" → `ffbb_next_match` · "prochains matchs" → `ffbb_club(action='calendrier')`
- **Catégorie ambiguë** : Appeler `ffbb_resolve_team` AVANT `ffbb_next_match`/`ffbb_last_result` si pas de numéro d'équipe

## Développement MCP (FastMCP)
- Cycle de vie : `mcp.run()` ou `mcp.run_streamable_http_async()` — pas de montage manuel via `app.mount()`
- Chemin personnalisé : configurer `mcp.settings.streamable_http_path` avant `mcp.run()`
- Routes HTTP : définies dans `routes.py` via `register_routes(mcp)`
- Tools MCP : définis dans `server.py` via `@mcp.tool()`

## Architecture
```
src/ffbb_mcp/
├── server.py          # Tools MCP + main() (≈1100 lignes)
├── routes.py          # Routes HTTP (health, metrics, dashboard, docs, etc.)
├── services.py        # Logique métier (≈2990 lignes)
├── cache_strategy.py  # TTL dynamique selon fenêtres de match
├── client.py          # FFBBDataClient factory + token refresh
├── metrics.py         # Prometheus metrics + health snapshot
├── utils.py           # serialize_model, parse_categorie, prune_payload
├── aliases.py         # Alias clubs + cache acronymes persistant
├── prompts.py         # Prompts MCP réutilisables
├── resources.py       # Resources MCP (ffbb://saisons, etc.)
├── dashboard.py       # Dashboard HTML
├── benchmark.py       # Benchmark performance
├── app_factory.py     # Starlette app + middlewares
├── _state.py          # State global (caches, inflight)
└── __init__.py        # Version du package
```

## Conventions de code
- Services : `ffbb_<nom>_service` (dans services.py)
- Tools MCP : `ffbb_<nom>` (dans server.py, `@mcp.tool()`)
- Pas de suffixe `_compact_` ou `_impl_` exposé
- Modifier une fonction à la fois, seulement si test/usage échoue
- Nouvelle fonction → test manuel validé avant exposition MCP
- **God files** : `services.py` (2990 lignes) — refactoring différé (cycles d'import)

## Commandes
- Tests : `.venv/bin/python -m pytest -q` (pas `pytest` seul)
- Pre-merge :
  1. pytest -q → 0 failed
  2. Test manuel du service : status='ok'
  3. `grep "compact\|fantôme" src/ffbb_mcp/*.py` → 0 résultat

## Push / Tag / Release Gate
Avant push/tag/release :
- `rtk uv run python tools/check_version_alignment.py`
- `rtk uv run ruff format --check .`
- `rtk uv run ruff check .`
- `rtk uv run mypy src`
- `rtk uv run pytest`
- Si version files modifiés : `rtk uv run tools/sync_version.py` + vérifier diff docs/website
- Vérifier cache (`acronyms_cache.json`) — revert mutations non liées
- Après push : inspecter les GitHub Actions

## Variables d'environnement
| Variable | Défaut | Usage |
|----------|--------|-------|
| `MCP_MODE` | `stdio` | Mode de transport (`stdio` / `streamable-http`) |
| `PORT` | `9123` | Port d'écoute HTTP |
| `HOST` | `0.0.0.0` | Interface d'écoute |
| `PUBLIC_URL` | `https://ffbb.desimone.fr` | URL publique pour liens/sitemap |
| `ALLOWED_HOSTS` | `*` | Hosts autorisés (DNS rebinding protection) |
| `ALLOWED_ORIGINS` | `*` | Origins CORS |
| `FFBB_LOG_LEVEL` | `INFO` | Niveau de log |
| `MAX_CONCURRENT_FFBB` | `8` | Concurrence max appels API FFBB |
| `FFBB_ENABLE_BENCHMARK` | `false` | Activer endpoint `/benchmark/run` (sécurité) |
| `FFBB_MCP_PRUNE_LIMIT` | `50` | Limite troncature payload |
| `FFBB_MAX_CALENDAR_MATCHES` | `300` | Max rencontres retournées |
| `FFBB_CACHE_TTL_*` | voir `cache_strategy.py` | TTL par type de cache |
| `TRUSTED_PROXY_HOSTS` | `127.0.0.1` | Proxies de confiance |

## graphify
- Présent dans graphify-out/ avec god nodes
- Lire `graphify-out/GRAPH_REPORT.md` avant les fichiers source
- Préférer `graphify query|path|explain` pour les questions cross-module
- Après modif code : `graphify update .`
