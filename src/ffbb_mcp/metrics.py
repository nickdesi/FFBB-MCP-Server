"""Module de tracking des métriques du serveur et des appels FFBB."""

import time
from threading import Lock

START_TIME = time.time()

# Compteurs globaux d'appels FFBB
_total_calls = 0
_error_calls = 0
_total_latency = 0.0

# Compteurs de cache (par nom de cache)
_cache_hits: dict[str, int] = {}
_cache_misses: dict[str, int] = {}

# Gauge simple pour suivre le nombre d'appels FFBB en vol
_ffbb_inflight = 0

_metrics_lock = Lock()


def record_call(latency: float, is_error: bool) -> None:
    """Enregistre un appel API FFBB (latence + erreurs)."""
    global _total_calls, _error_calls, _total_latency
    with _metrics_lock:
        _total_calls += 1
        _total_latency += latency
        if is_error:
            _error_calls += 1


def inc_inflight() -> None:
    """Incrémente le nombre d'appels FFBB en cours."""
    global _ffbb_inflight
    with _metrics_lock:
        _ffbb_inflight += 1


def dec_inflight() -> None:
    """Décrémente le nombre d'appels FFBB en cours (jamais en dessous de 0)."""
    global _ffbb_inflight
    with _metrics_lock:
        _ffbb_inflight = max(0, _ffbb_inflight - 1)


def record_cache_hit(cache_name: str) -> None:
    """Enregistre un hit de cache pour le cache donné."""
    with _metrics_lock:
        _cache_hits[cache_name] = _cache_hits.get(cache_name, 0) + 1


def record_cache_miss(cache_name: str) -> None:
    """Enregistre un miss de cache pour le cache donné."""
    with _metrics_lock:
        _cache_misses[cache_name] = _cache_misses.get(cache_name, 0) + 1


def generate_prometheus_metrics() -> str:
    """Génère les métriques au format texte (compatible Prometheus/Coolify)."""
    uptime = time.time() - START_TIME
    with _metrics_lock:
        calls = _total_calls
        errors = _error_calls
        latency_total = _total_latency
        inflight = _ffbb_inflight
        cache_hits_snapshot = dict(_cache_hits)
        cache_misses_snapshot = dict(_cache_misses)

    error_rate = (errors / calls) if calls > 0 else 0.0
    avg_latency = (latency_total / calls) if calls > 0 else 0.0

    lines: list[str] = [
        "# HELP ffbb_uptime_seconds Uptime du serveur en secondes",
        "# TYPE ffbb_uptime_seconds gauge",
        f"ffbb_uptime_seconds {uptime:.2f}",
        "",
        "# HELP ffbb_api_calls_total Total des appels vers l'API FFBB",
        "# TYPE ffbb_api_calls_total counter",
        f"ffbb_api_calls_total {calls}",
        "",
        "# HELP ffbb_api_errors_total Total des erreurs retournées par l'API FFBB",
        "# TYPE ffbb_api_errors_total counter",
        f"ffbb_api_errors_total {errors}",
        "",
        "# HELP ffbb_api_error_rate Taux d'erreur FFBB",
        "# TYPE ffbb_api_error_rate gauge",
        f"ffbb_api_error_rate {error_rate:.4f}",
        "",
        "# HELP ffbb_api_latency_seconds_total Latence cumulative des appels API",
        "# TYPE ffbb_api_latency_seconds_total counter",
        f"ffbb_api_latency_seconds_total {latency_total:.4f}",
        "",
        "# HELP ffbb_api_avg_latency_seconds Latence moyenne par appel",
        "# TYPE ffbb_api_avg_latency_seconds gauge",
        f"ffbb_api_avg_latency_seconds {avg_latency:.4f}",
        "",
        "# HELP ffbb_api_inflight_requests Nombre d'appels FFBB en cours",
        "# TYPE ffbb_api_inflight_requests gauge",
        f"ffbb_api_inflight_requests {inflight}",
    ]

    # Sérialiser les hits/miss de cache par label "cache"
    if cache_hits_snapshot or cache_misses_snapshot:
        lines.extend(
            [
                "",
                "# HELP ffbb_cache_hits_total Hits de cache par cache",
                "# TYPE ffbb_cache_hits_total counter",
            ]
        )
        for name, value in cache_hits_snapshot.items():
            lines.append(f'ffbb_cache_hits_total{{cache="{name}"}} {value}')

        lines.extend(
            [
                "",
                "# HELP ffbb_cache_misses_total Miss de cache par cache",
                "# TYPE ffbb_cache_misses_total counter",
            ]
        )
        for name, value in cache_misses_snapshot.items():
            lines.append(f'ffbb_cache_misses_total{{cache="{name}"}} {value}')

    return "\n".join(lines) + "\n"
