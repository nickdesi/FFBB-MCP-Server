# Performance: Benchmarks and Optimizations

This document summarizes recent performance optimizations and explains how to run the lightweight benchmarks included in the repository.

## Summary of core optimizations

- **Global concurrency limiter**: all outbound FFBB calls pass through an `asyncio.Semaphore` controlled by the `MAX_CONCURRENT_FFBB` environment variable (default: 8). This prevents thundering-herd effects and keeps the upstream API under control.
- **Per-key inflight deduplication**: detail endpoints (`competition`, `poule`, `organisme`) and higher-level workflows (`ffbb_bilan_service`, `get_calendrier_club_service`) use an inflight map to deduplicate concurrent calls on the same key.
- **Shared in-memory TTL caches**: `cachetools.TTLCache` instances are shared between tools and resources for popular read paths (lives, saisons, search results, details, calendrier, bilan).
- **Lazy imports**: heavy Meilisearch-related symbols from `ffbb_api_client_v3` are imported lazily inside hot functions (`_search_generic`, `multi_search_service`) to reduce cold-start overhead.
- **Regex precompilation**: the filtering logic in `ffbb_equipes_club_service` relies on precompiled regular expressions to avoid re-compiling them on every call.

## Concurrency and batching

Outbound calls to the FFBB API are governed by two layers:

1. A **global semaphore** (`MAX_CONCURRENT_FFBB`) that caps total concurrent requests.
2. A per-workflow semaphore (`FFBB_POULE_FETCH_CONCURRENCY`) used when fetching many poules in parallel for `ffbb_bilan_service` and `get_calendrier_club_service`.

In addition, all FFBB calls go through a `_safe_call` wrapper that applies retry with exponential backoff and structured logging. For observability, a variant `_safe_call_with_inflight` increments/decrements a gauge that tracks the number of in-flight FFBB calls.

## Observability and Prometheus metrics

The `/metrics` endpoint exposes Prometheus-style metrics that reflect both usage and performance.

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

1. Activate the project's virtualenv:

```bash
source .venv/bin/activate
```

2. Run the lightweight benchmark that measures `ffbb_bilan_service` and `get_calendrier_club_service` using internal mocks:

```bash
python tools/measure_services.py
```

This script runs 100 iterations by default and prints mean/median/p95 timings. It exercises the code paths without relying on the external FFBB API.

## Running realistic benchmarks (network latency simulation)

To approximate real-world conditions, you can simulate network latency without an external server by setting an environment variable when running the benchmark script:

```bash
# simulate 150ms latency per API call
SIMULATE_LATENCY_MS=150 python tools/measure_services.py
```

## CI benchmark job (GitHub Actions)

A small CI job is provided to run the same lightweight benchmark on every push. See `.github/workflows/benchmark.yml`.

The benchmark script supports two environment variables to enforce P95 thresholds (in seconds):

- `THRESHOLD_P95_BILAN` — threshold for `ffbb_bilan_service`.
- `THRESHOLD_P95_CAL` — threshold for `get_calendrier_club_service`.

Example (CI job that fails if P95 > 0.5s):

```bash
THRESHOLD_P95_BILAN=0.5 THRESHOLD_P95_CAL=0.5 python tools/measure_services.py
```

To enable CI failure on thresholds, set the environment variables in the workflow.

## Notes and next steps

- For production-grade profiling, run the benchmark against a staging FFBB API or a dedicated simulator that reproduces real endpoints and payloads.
- Consider adding structured timing logs around network calls to gather real latencies from running instances (simple JSON logs are sufficient and don't require Prometheus).
- If desired we can add an optional small HTTP simulator that mimics the FFBB API endpoints and injects configurable latency and error rates.
