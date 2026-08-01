# Performance: Benchmarks and Optimizations

This document summarizes recent performance optimizations and explains how to run the lightweight benchmarks included in the repository.

## Summary of core optimizations

- **Global concurrency limiter**: all outbound FFBB calls pass through an `asyncio.Semaphore` controlled by the `MAX_CONCURRENT_FFBB` environment variable (default: 8). This prevents thundering-herd effects and keeps the upstream API under control.
- **Per-key inflight deduplication**: detail endpoints (`competition`, `poule`, `organisme`) and higher-level workflows (`ffbb_bilan_service`, `get_calendrier_club_service`) use an inflight map to deduplicate concurrent calls on the same key.
- **Shared in-memory TTL caches**: `cachetools.TTLCache` instances are shared between tools and resources for popular read paths (lives, saisons, search results, details, calendrier, bilan).
- **Lazy imports**: heavy Meilisearch-related symbols from `ffbb_data_client` are imported lazily inside hot functions (`_search_generic`, `multi_search_service`) to reduce cold-start overhead.
- **Regex precompilation**: the filtering logic in `ffbb_equipes_club_service` relies on precompiled regular expressions to avoid re-compiling them on every call.
- **Parallel fan-out**: workflows agrégés (`ffbb_bilan_service`, `get_calendrier_club_service`, `ffbb_equipes_club_service`) récupèrent les poules/classements en `asyncio.gather` — N appels indépendants coûtent un seul RTT (~412ms) au lieu de N×412ms.
- **Stale-While-Revalidate (SWR)**: les chemins chauds (`lives`, `saisons`, `poule`, `classement`) renvoient la valeur en cache immédiatement même si elle approche de l'expiration, et la rafraîchissent en arrière-plan (`FFBB_SWR_ENABLED`, `FFBB_SWR_STALE_FRACTION`). Le TTL dynamique des poules/classements (via `get_poule_ttl`) sert de seuil de fraîcheur. L'utilisateur ne subit jamais la latence d'un miss sur ces données.
- **Cache persistant (SQLite)**: activé par défaut (`FFBB_SERVICE_CACHE_PERSIST=1`), il survit aux redémarrages (critique en mode stdio où chaque session démarre dans un processus neuf) sans jamais servir de donnée périmée.
- **Warm-up au démarrage**: en mode HTTP, une boucle rafraîchit proactivement les `lives` pendant les fenêtres de match (`FFBB_LIVES_REFRESH_INTERVAL`) et un préchauffage optionnel charge les organismes/clubs configurés (`FFBB_WARMUP_ORGANISMES`).
- **Endpoints de préchauffage bornés**: `POST /cache/warmup` refuse les listes de plus de `FFBB_WARMUP_MAX_ORGANISMES` organismes (défaut 50) et les bodies > 64 Ko (`413`), valide strictement `organisme_ids` (`400`), et exige `Authorization: Bearer <clé>` dès que `FFBB_WARMUP_API_KEY` est configurée (`401` sinon). Le service tronque également toute liste excessive en défense en profondeur — le sémaphore limite la concurrence, ces bornes limitent le volume total (CWE-400).

## Concurrency and batching

Outbound calls to the FFBB API are governed by two layers:

1. A **global semaphore** (`MAX_CONCURRENT_FFBB`) that caps total concurrent requests.
2. A per-workflow semaphore (`FFBB_POULE_FETCH_CONCURRENCY`) used when fetching many poules in parallel for `ffbb_bilan_service` and `get_calendrier_club_service`.

In addition, all FFBB calls go through a `_safe_call` wrapper that applies retry with exponential backoff and structured logging. For observability, a variant `_safe_call_with_inflight` increments/decrements a gauge that tracks the number of in-flight FFBB calls.

## Observability and Prometheus metrics

The `/metrics` endpoint exposes Prometheus-style metrics that reflect both usage and performance. Two companion routes are also available:

- `/metrics.json` — JSON snapshot for lightweight dashboards or automation.
- `/dashboard` — built-in HTML dashboard for manual monitoring.

### Global FFBB call metrics

- `ffbb_uptime_seconds` — process uptime since start.
- `ffbb_api_calls_total` — total number of FFBB API calls observed (after retries).
- `ffbb_api_errors_total` — number of calls that ended in error.
- `ffbb_api_error_rate` — ratio `errors / max(1, total)`.
- `ffbb_api_latency_seconds_total` — accumulated latency across all calls.
- `ffbb_api_avg_latency_seconds` — average latency derived from totals.
- `ffbb_api_inflight_requests` — gauge tracking how many FFBB calls are currently in progress.

All network calls in the services layer are wrapped with `_safe_call_with_inflight`, so these metrics reflect the real production traffic.

### Cache metrics

Each logical cache exposes two counters, keyed by the cache name:

- `ffbb_cache_hits_total{cache="<name>"}` — number of times a value was served from in-memory cache.
- `ffbb_cache_misses_total{cache="<name>"}` — number of times a value had to be fetched from the upstream API.

Cache names currently include:

- `lives` — cache for live games.
- `saisons` — cache for the seasons list.
- `search` — cache for Meilisearch-based search results.
- `detail` — cache for competition, poule and organisme details.
- `calendrier` — cache for calendrier-club results.
- `bilan` — cache for full club bilan results.

These metrics allow you to verify that hot paths are effectively cached and to tune TTLs or cache keys if necessary.

## Local benchmarking (fast, mock-based)

Run the lightweight benchmark that measures `ffbb_bilan_service` and `get_calendrier_club_service` using internal mocks:

```bash
uv run python tools/measure_services.py
```

Windows fallback if `uv` is not available but the local virtualenv exists:

```powershell
.\.venv\Scripts\python.exe tools\measure_services.py
```

This script runs 100 iterations by default and prints mean/median/p95 timings. It exercises the code paths without relying on the external FFBB API.

## Running realistic benchmarks (network latency simulation)

To approximate real-world conditions, you can simulate network latency without an external server by setting an environment variable when running the benchmark script:

```bash
# simulate 150ms latency per API call
SIMULATE_LATENCY_MS=150 uv run python tools/measure_services.py
```

PowerShell equivalent:

```powershell
$env:SIMULATE_LATENCY_MS = "150"
uv run python tools/measure_services.py
Remove-Item Env:SIMULATE_LATENCY_MS
```

## CI benchmark job (GitHub Actions)

A small CI job is provided to run the same lightweight benchmark on every push. See `.github/workflows/benchmark.yml`.

The benchmark script supports two environment variables to enforce P95 thresholds (in seconds):

- `THRESHOLD_P95_BILAN` — threshold for `ffbb_bilan_service`.
- `THRESHOLD_P95_CAL` — threshold for `get_calendrier_club_service`.

Example (CI job that fails if P95 > 0.5s):

```bash
THRESHOLD_P95_BILAN=0.5 THRESHOLD_P95_CAL=0.5 uv run python tools/measure_services.py
```

PowerShell equivalent:

```powershell
$env:THRESHOLD_P95_BILAN = "0.5"
$env:THRESHOLD_P95_CAL = "0.5"
uv run python tools/measure_services.py
Remove-Item Env:THRESHOLD_P95_BILAN
Remove-Item Env:THRESHOLD_P95_CAL
```

To enable CI failure on thresholds, set the environment variables in the workflow.

## Notes and next steps

- For production-grade profiling, run the benchmark against a staging FFBB API or a dedicated simulator that reproduces real endpoints and payloads.
- Consider adding structured timing logs around network calls to gather real latencies from running instances (simple JSON logs are sufficient and don't require Prometheus).
- If desired we can add an optional small HTTP simulator that mimics the FFBB API endpoints and injects configurable latency and error rates.
