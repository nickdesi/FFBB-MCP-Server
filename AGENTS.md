# FFBB MCP Server

> ⚠️ **Fichier auto-généré** par `tools/update_agents_md.py` — ne pas modifier manuellement.
> Dernière mise à jour : FFBB MCP server | server.py: 1233 lignes | services.py: 4101 lignes

## Langue
Tous les documents de travail (walkthrough.md, implementation_plan.md) DOIVENT être en français.

## Persona
Expert en basketball français. Accès au serveur MCP FFBB (ffbb.desimone.fr) connecté aux données officielles FFBB.

## Workflow FFBB (Outils MCP)
1. **ffbb_search** → Recherche FFBB — clubs, compétitions, matchs, salles, tournois, etc
2. **ffbb_resolve_team** → Identifie une equipe unique (Pivot central)
3. **ffbb_team_summary** → Résumé complet et agent-friendly pour une équipe
4. **ffbb_bilan** → Bilan complet d'une équipe toutes phases confondues en UN seul appel
5. **ffbb_club** → Outils agreges autour d'un club (calendrier, equipes, classement)
6. **ffbb_get** → Recupere une ressource FFBB par identifiant
7. **ffbb_next_match** → Prochain match à jouer pour une équipe précise
8. **ffbb_last_result** → Dernier résultat d'une équipe précise
9. **ffbb_lives** → Matchs en cours (scores live, cache 30s). Retourne [] si aucun match
10. **ffbb_bilan_saison** → Bilan détaillé de la saison pour une équipe précise (toutes phases)
11. **ffbb_saisons** → Liste des saisons FFBB. active_only=True pour la saison en cours uniquement
12. **ffbb_version** → Informations de version et configuration runtime du serveur FFBB MCP

## Ressources MCP
- `ffbb://saisons` → Liste des saisons FFBB au format JSON
- `ffbb://competition/{competition_id}` → Détails d'une compétition au format JSON
- `ffbb://poule/{poule_id}` → Détails d'une poule au format JSON
- `ffbb://organisme/{organisme_id}` → Détails d'un organisme/club au format JSON

## Règles de comportement
- Appelle TOUJOURS un outil MCP avant de répondre
- OBLIGATION ABSOLUE : Utiliser TOUJOURS le préfixe 'rtk' pour TOUTES les commandes shell exécutées dans le terminal (ex: 'rtk uv run ...', 'rtk git ...')
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

## Karpathy Guidelines (Règles de développement)
Ces directives inspirées d'Andrej Karpathy visent à éliminer les erreurs de codage courantes en privilégiant la simplicité et la rigueur :

### 1. Penser avant de coder (Think Before Coding)
- **Ne pas assumer, ne pas cacher la confusion, expliciter les compromis.**
- Avant d'implémenter :
  - Déclarez vos hypothèses de manière explicite. En cas d'incertitude, demandez.
  - S'il existe plusieurs interprétations, présentez-les — ne choisissez pas en silence.
  - Si une approche plus simple existe, proposez-la. Argumentez contre la complexité inutile si nécessaire.
  - Si quelque chose n'est pas clair, arrêtez-vous. Nommez ce qui vous perturbe et demandez confirmation.

### 2. La simplicité d'abord (Simplicity First)
- **Le minimum de code nécessaire pour résoudre le problème. Rien de spéculatif.**
- Pas de fonctionnalités au-delà de ce qui est explicitement demandé.
- Pas d'abstractions pour du code à usage unique.
- Pas de "flexibilité" ou de "configurabilité" non requise.
- Pas de gestion d'erreurs pour des scénarios impossibles.
- Si vous écrivez 200 lignes alors que 50 suffiraient, réécrivez-le.
- Posez-vous toujours la question : "Est-ce qu'un développeur senior validerait cette implémentation comme simple et directe ?"

## Phases éliminatoires vs poules

### Détection automatique
Si le champ `competition` contient (insensible à la casse) l'un de ces
termes : `finale`, `1/2`, `demi-finale`, `demi-fin`, `quart`, `play-off`, `playoff`, `coupe`, `barrage`, `promotion`
→ **Phase éliminatoire** 🏆
Sinon (Phase 1, Phase 2, Phase 3…) → **Phase de poule** 📊

### Règles de formulation
- Phase éliminatoire : toujours mentionner explicitement le contexte
  (ex : "ce match est une demi-finale départementale")
- Ne JAMAIS rattacher un match éliminatoire au bilan de phase de poule

### État d'une phase (terminée vs en cours)
`phase_courante` dans `ffbb_bilan` = **dernière phase connue**, pas
nécessairement une phase active.

Règle de temps verbal :
- Si aucun match futur détectable dans la poule → utiliser le **passé**
  ("ont terminé", "ont fini", "se sont classés")
- Si des matchs restent à jouer → utiliser le **présent**
  ("sont", "occupent", "se trouvent")

⚠️ INTERDIT : écrire "sont actuellement Xe" si la phase est terminée.

### Format enrichi pour tout match affiché
- 📍 Domicile / Extérieur
- 🏆 Phase éliminatoire OU 📊 Phase de poule (numéro)
- ⚠️ Si `salle` ou `ville` vides → écrire "Salle non encore renseignée"
- 📍 Format d'adresse standardisé : `[Nom de la Salle] - [Adresse Postale], [Ville]` (gérer proprement les valeurs manquantes sans séparateurs orphelins)

## Développement MCP (FastMCP)
- Cycle de vie : `mcp.run()` ou `mcp.run_streamable_http_async()` — pas de montage manuel via `app.mount()`
- Chemin personnalisé : configurer `mcp.settings.streamable_http_path` avant `mcp.run()`
- Routes HTTP : définies dans `routes.py` via `register_routes(mcp)`
- Tools MCP : définis dans `server.py` via `@mcp.tool()`

## Architecture
```
src/ffbb_mcp/
├── __init__.py            # Version du package
├── __main__.py            # Point d'entrée CLI
├── _state.py              # State global (caches, inflight)
├── aliases.py             # Alias clubs + cache acronymes persistant
├── app_factory.py         # Starlette app + middlewares
├── benchmark.py           # Benchmark performance
├── cache_strategy.py      # TTL dynamique selon fenêtres de match
├── client.py              # FFBBDataClient factory + token refresh
├── dashboard.py           # Dashboard HTML
├── metrics.py             # Prometheus metrics + health snapshot
├── prompts.py             # Prompts MCP réutilisables
├── resources.py           # Resources MCP (ffbb://saisons, etc.)
├── routes.py              # Routes HTTP (health, metrics, dashboard, docs, etc.)
├── server.py              # Tools MCP + main() (≈1233 lignes)
├── services/              # Logique métier modularisée (≈4101 lignes)
│   ├── __init__.py        # Point d'entrée et factory de services
│   ├── club.py            # Service de gestion des clubs
│   ├── common.py          # Helpers et base services partagés
│   ├── poule.py           # Service de gestion des poules
│   ├── salle.py           # Service de gestion des salles
│   ├── search.py          # Service de recherche multicritère
│   └── warmup.py          # Service de préchauffage du cache
└── utils.py               # serialize_model, parse_categorie, prune_payload
```

## Conventions de code
- Services : `ffbb_<nom>_service` (dans services/)
- Tools MCP : `ffbb_<nom>` (dans server.py, `@mcp.tool()`)
- Pas de suffixe `_compact_` ou `_impl_` exposé
- Modifier une fonction à la fois, seulement si test/usage échoue
- Nouvelle fonction → test manuel validé avant exposition MCP
- **Modularisation** : Le package `services/` (total ≈4101 lignes) remplace l'ancien fichier unique de 2915 lignes pour une meilleure cohésion.

## Commandes
- Démarrer le serveur MCP (stdio) : `rtk uv run python -m ffbb_mcp` (recommandé pour Claude Desktop)
- Démarrer le serveur MCP (HTTP/SSE) : `MCP_MODE=streamable-http rtk uv run python -m ffbb_mcp` (port `9123` par défaut)
- Inspecter/Tester localement : `rtk npx -y @modelcontextprotocol/inspector uv run python -m ffbb_mcp`
- Tests unitaires : `.venv/bin/python -m pytest -q` (pas `pytest` seul)
- Pre-merge :
  1. pytest -q → 0 failed
  2. Test manuel du service : status='ok'
  3. `grep "compact\|fantôme" src/ffbb_mcp/*.py` → 0 résultat

## Graphify

Outil d'analyse de graphe de code installé via `uv tools` (`rtk graphify`).
`graphify-out/` est gitignore — artefacts locaux, jamais versionnés.

**Sorties** : `graph.html` (visualisation interactive) · `GRAPH_REPORT.md` (god nodes, connexions surprenantes, questions suggérées) · `graph.json` (graphe persistant)

**Mise à jour du graphe**
- Après chaque push modifiant le code source : `rtk graphify update .`
- Après un refactor majeur (moins de nœuds) : `rtk graphify update . --force`
- Recalcul des clusters sans re-extraction : `rtk graphify cluster-only .`

**Requêtes**
- Interroger le graphe : `rtk graphify query "<question>"`
- Chemin entre deux nœuds : `rtk graphify path "ServiceA" "ServiceB"`
- Explication d'un nœud : `rtk graphify explain "NomDuModule"`
- Modules impactés par un fichier : `rtk graphify affected <fichier>`

**Architecture & automatisation**
- Page Mermaid call-flow : `rtk graphify export callflow-html`
- Hook post-commit (rebuild auto) : `rtk graphify hook install`
- Statut du hook : `rtk graphify hook status`

## Push / Tag / Release Gate
⚠️ OBLIGATION STRICTE : Toutes ces commandes DOIVENT être préfixées par 'rtk' dans le terminal (ex: 'rtk uv run pytest'). Ne jamais exécuter de commande nue sans 'rtk'.
Avant push/tag/release :
- `rtk uv run python tools/check_version_alignment.py`
- `rtk uv run ruff format --check .`
- `rtk uv run ruff check .`
- `rtk uv run mypy src`
- `rtk uv run pytest`
- Si version files modifiés : `rtk uv run tools/sync_version.py` + vérifier diff docs/website
- Vérifier cache (`src/ffbb_mcp/acronyms_cache.json`) — revert impératif de toute modification non liée à votre tâche
- Après push : inspecter les GitHub Actions

## Variables d'environnement
| Variable | Défaut | Usage |
|----------|--------|-------|
| `XDG_CACHE_HOME` | `` | Dossier racine pour stocker les fichiers de cache persistants (ex: acronymes, benchmark) |
| `MCP_MODE` | `stdio` | Mode de transport (`stdio` / `streamable-http`) |
| `TRUSTED_PROXY_HOSTS` | `127.0.0.1` | Proxies de confiance |
| `FFBB_LIVES_REFRESH_INTERVAL` | `10` | Intervalle de rafraîchissement proactif des lives en secondes, mode HTTP (défaut : 10) |
| `FFBB_CACHE_BACKEND` | `sqlite` | Choix du backend de cache HTTP (`sqlite` ou `redis`) |
| `FFBB_SERVICE_CACHE_PERSIST` | `1` | Activer la persistance des caches service sur disque (SQLite) entre redémarrages |
| `FFBB_KNOWN_CLUB_IDS` | `` | Override JSON de la liste d'organisme_id connus pour les prompts MCP (fallback : _DEFAULT_KNOWN_CLUB_IDS) |
| `FFBB_ENABLE_BENCHMARK` | `` | Activer endpoint `/benchmark/run` (sécurité) |
| `ALLOWED_HOSTS` | `*` | Hosts autorisés (DNS rebinding protection) |
| `ALLOWED_ORIGINS` | `*` | Origins CORS |
| `PUBLIC_URL` | `https://ffbb.desimone.fr` | URL publique pour liens/sitemap |
| `ENABLE_DNS_PROTECTION` | `` | Activer/désactiver explicitement la protection contre le DNS rebinding |
| `FFBB_LOG_LEVEL` | `INFO` | Niveau de log |
| `HOST` | `0.0.0.0` | Interface d'écoute |
| `PORT` | `9123` | Port d'écoute HTTP |
| `FFBB_SWR_ENABLED` | `1` | Activer le Stale-While-Revalidate : servir le cache et rafraîchir en arrière-plan (défaut : 1) |
| `FFBB_SWR_STALE_FRACTION` | `0.75` | Fraction du TTL au-delà de laquelle une entrée est rafraîchie en arrière-plan (défaut : 0.75) |
| `MAX_CONCURRENT_FFBB` | `8` | Concurrence max appels API FFBB |
| `FFBB_MAX_CALENDAR_MATCHES` | `300` | Max rencontres retournées |
| `FFBB_WARMUP_ORGANISMES` | `` | Liste d'organisme_id séparés par des virgules à préchauffer au démarrage |
| `FFBB_WARMUP_CONCURRENCY` | `5` | Concurrence maximale lors du préchauffage du cache |
| `FFBB_MCP_PRUNE_LIMIT` | `50` | Limite troncature payload |
| `FFBB_POULE_FETCH_CONCURRENCY` | — | Concurrence max fetch poules |
| `FFBB_CACHE_TTL_*` | — | TTL par type de cache (voir cache_strategy.py) |
| `FFBB_REDIS_URL` | — | URL de connexion à l'instance Redis si backend=redis |
| `FFBB_CACHE_EXPIRE_AFTER` | — | TTL en secondes pour le cache HTTP court de session (défaut : 30) |

## Notes workflow / outils

### PR Comments pour Jules (Google)
- **NE PAS utiliser** `gh pr review --comment` — Jules ne le détecte pas
- **Utiliser** `gh pr comment <number> --body "..."` ou commenter via l'UI GitHub
- Jules écoute les `issue_comment` events, pas les `pull_request_review` events
