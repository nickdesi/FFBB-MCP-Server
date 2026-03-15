# Performance: Benchmarks and Optimizations

This document summarizes recent performance optimizations and explains how to run the lightweight benchmarks included in the repository.

Summary of optimizations applied
- Avoid heavy imports at module import time (lazy imports for Meilisearch models/config).
- Fallback handling for non-numeric `poule_id` to support mocked IDs without exceptions.
- `ffbb_equipes_club_service` now accepts `org_data` to reuse a preloaded organisme and avoid duplicate API calls.
- Precompiled regular expressions for filtering to reduce repeated compilation costs.

Local benchmarking (fast, mock-based)

1. Activate the project's virtualenv:

```bash
source .venv/bin/activate
```

2. Run the lightweight benchmark that measures `ffbb_bilan_service` and `get_calendrier_club_service` using internal mocks:

```bash
python tools/measure_services.py
```

This script runs 100 iterations by default and prints mean/median/p95 timings. It exercises the code paths without relying on the external FFBB API.

CI benchmark job (GitHub Actions)

A small CI job is provided to run the same lightweight benchmark on every push. See `.github/workflows/benchmark.yml`.

Next steps for realistic measurements
- Run the benchmark against a network simulator or a staging FFBB API to capture real latencies.
- Add timing instrumentation (structured logs) around network calls to measure end-to-end latencies in production.
- Consider adding CI thresholds that fail a run when P95 latency exceeds a chosen SLO.

If you want, I can add the real-API simulator (a tiny local HTTP server that injects latency) or add SLO checks to the CI job.

Running realistic benchmarks (network latency simulation)

To approximate real-world conditions, you can simulate network latency without an external server by setting an environment variable when running the benchmark script:

```bash
# simulate 150ms latency per API call
SIMULATE_LATENCY_MS=150 python tools/measure_services.py
```

CI thresholds (fail if P95 too high)

The benchmark script supports two environment variables to enforce P95 thresholds (in seconds):

- `THRESHOLD_P95_BILAN` — threshold for `ffbb_bilan_service`
- `THRESHOLD_P95_CAL` — threshold for `get_calendrier_club_service`

Example (CI job that fails if P95 > 0.5s):

```bash
THRESHOLD_P95_BILAN=0.5 THRESHOLD_P95_CAL=0.5 python tools/measure_services.py
```

The provided GitHub Actions workflow (`.github/workflows/benchmark.yml`) runs the lightweight benchmark. To enable CI failure on thresholds, set the environment variables in the workflow.

Notes and next steps
- For production-grade profiling, run the benchmark against a staging FFBB API or a dedicated simulator that reproduces real endpoints and payloads.
- Consider adding structured timing logs around network calls to gather real latencies from running instances (simple JSON logs are sufficient and don't require Prometheus).
- If desired I can add an optional small HTTP simulator that mimics the FFBB API endpoints and injects configurable latency and error rates.
