"""Module de tracking des métriques du serveur et des appels FFBB."""

import time
from threading import Lock
from typing import Any

START_TIME = time.time()

# Compteurs globaux d'appels FFBB
_total_calls: int = 0
_error_calls: int = 0
_total_latency: float = 0.0

# Compteurs de cache (par nom de cache)
_cache_hits: dict[str, int] = {}
_cache_misses: dict[str, int] = {}

# Gauge : appels FFBB en vol
_ffbb_inflight: int = 0

_metrics_lock = Lock()


# ---------------------------------------------------------------------------
# Enregistrement
# ---------------------------------------------------------------------------


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
    """Enregistre un hit de cache."""
    with _metrics_lock:
        _cache_hits[cache_name] = _cache_hits.get(cache_name, 0) + 1


def record_cache_miss(cache_name: str) -> None:
    """Enregistre un miss de cache.

    À appeler uniquement depuis _cache_get (pas depuis _cache_set) pour
    éviter le double-comptage.
    """
    with _metrics_lock:
        _cache_misses[cache_name] = _cache_misses.get(cache_name, 0) + 1


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def get_snapshot() -> dict[str, Any]:
    """Retourne un snapshot instantané des métriques (thread-safe).

    Utile pour les tests, un endpoint /metrics JSON ou le logging périodique.
    Les métriques dérivées (error_rate, avg_latency, hit_ratio) sont calculées
    hors du lock pour minimiser la durée de contention.
    """
    with _metrics_lock:
        calls = _total_calls
        errors = _error_calls
        latency_total = _total_latency
        inflight = _ffbb_inflight
        hits = dict(_cache_hits)
        misses = dict(_cache_misses)

    error_rate = errors / calls if calls > 0 else 0.0
    avg_latency = latency_total / calls if calls > 0 else 0.0

    cache_stats: dict[str, dict[str, Any]] = {}
    all_cache_names = set(hits) | set(misses)
    for name in all_cache_names:
        h = hits.get(name, 0)
        m = misses.get(name, 0)
        total = h + m
        cache_stats[name] = {
            "hits": h,
            "misses": m,
            "total": total,
            "hit_ratio": h / total if total > 0 else 0.0,
        }

    total_hits = sum(hits.values())
    total_misses = sum(misses.values())
    total_cache = total_hits + total_misses

    return {
        "uptime_seconds": time.time() - START_TIME,
        "api_calls_total": calls,
        "api_errors_total": errors,
        "api_error_rate": error_rate,
        "api_latency_seconds_total": latency_total,
        "api_avg_latency_seconds": avg_latency,
        "api_inflight_requests": inflight,
        "cache": cache_stats,
        "cache_hits_total": total_hits,
        "cache_misses_total": total_misses,
        "cache_hit_ratio_global": total_hits / total_cache if total_cache > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Export Prometheus
# ---------------------------------------------------------------------------


def generate_prometheus_metrics() -> str:
    """Génère les métriques au format texte Prometheus (exposition standard).

    Les métriques dérivées (error_rate, avg_latency) sont intentionnellement
    absentes : un scraper Prometheus les calcule via rate() / irate().
    Elles restent disponibles via get_snapshot() pour les besoins internes.
    """
    snap = get_snapshot()
    uptime = snap["uptime_seconds"]
    days = int(uptime // 86400)
    hours = int((uptime % 86400) // 3600)
    minutes = int((uptime % 3600) // 60)
    uptime_fmt = f"{days:03d}:{hours:02d}:{minutes:02d}"

    lines: list[str] = [
        "# HELP ffbb_uptime_seconds Uptime du serveur en secondes",
        "# TYPE ffbb_uptime_seconds gauge",
        f"ffbb_uptime_seconds {uptime:.2f}",
        "",
        "# HELP ffbb_uptime_formatted Uptime lisible (JJJ:HH:MM)",
        "# TYPE ffbb_uptime_formatted gauge",
        f'ffbb_uptime_formatted{{human="{uptime_fmt}"}} 1',
        "",
        "# HELP ffbb_api_calls_total Total des appels vers l'API FFBB",
        "# TYPE ffbb_api_calls_total counter",
        f"ffbb_api_calls_total {snap['api_calls_total']}",
        "",
        "# HELP ffbb_api_errors_total Total des erreurs retournées par l'API FFBB",
        "# TYPE ffbb_api_errors_total counter",
        f"ffbb_api_errors_total {snap['api_errors_total']}",
        "",
        "# HELP ffbb_api_latency_seconds_total Latence cumulative des appels API (secondes)",
        "# TYPE ffbb_api_latency_seconds_total counter",
        f"ffbb_api_latency_seconds_total {snap['api_latency_seconds_total']:.4f}",
        "",
        "# HELP ffbb_api_inflight_requests Nombre d'appels FFBB en cours",
        "# TYPE ffbb_api_inflight_requests gauge",
        f"ffbb_api_inflight_requests {snap['api_inflight_requests']}",
    ]

    cache_stats: dict[str, dict] = snap["cache"]
    if cache_stats:
        lines += [
            "",
            "# HELP ffbb_cache_hits_total Hits de cache par cache",
            "# TYPE ffbb_cache_hits_total counter",
        ]
        for name, stat in cache_stats.items():
            lines.append(f'ffbb_cache_hits_total{{cache="{name}"}} {stat["hits"]}')

        lines += [
            "",
            "# HELP ffbb_cache_misses_total Miss de cache par cache",
            "# TYPE ffbb_cache_misses_total counter",
        ]
        for name, stat in cache_stats.items():
            lines.append(f'ffbb_cache_misses_total{{cache="{name}"}} {stat["misses"]}')

        lines += [
            "",
            "# HELP ffbb_cache_hit_ratio Ratio hits/(hits+misses) par cache [0-1]",
            "# TYPE ffbb_cache_hit_ratio gauge",
        ]
        for name, stat in cache_stats.items():
            lines.append(
                f'ffbb_cache_hit_ratio{{cache="{name}"}} {stat["hit_ratio"]:.4f}'
            )

    lines += [
        "",
        "# HELP ffbb_cache_hits_global_total Total hits toutes caches confondues",
        "# TYPE ffbb_cache_hits_global_total counter",
        f"ffbb_cache_hits_global_total {snap['cache_hits_total']}",
        "",
        "# HELP ffbb_cache_misses_global_total Total misses toutes caches confondues",
        "# TYPE ffbb_cache_misses_global_total counter",
        f"ffbb_cache_misses_global_total {snap['cache_misses_total']}",
        "",
        "# HELP ffbb_cache_hit_ratio_global Ratio hits/total global [0-1]",
        "# TYPE ffbb_cache_hit_ratio_global gauge",
        f"ffbb_cache_hit_ratio_global {snap['cache_hit_ratio_global']:.4f}",
    ]

    return "\n".join(lines) + "\n"
