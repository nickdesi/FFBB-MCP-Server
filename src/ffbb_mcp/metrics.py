"""Module de tracking des métriques du serveur et des appels FFBB."""

from __future__ import annotations

import bisect
import time
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

START_TIME = time.time()

# Buckets de latence pour le histogram (secondes) — valeurs adaptées aux appels FFBB
_LATENCY_BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

# Compteurs d'appels par statut
_calls_success: int = 0
_calls_error: int = 0

# Histogram de latence : bucket_counts[i] = nb observations <= _LATENCY_BUCKETS[i]
# Index len(_LATENCY_BUCKETS) = +Inf bucket
_latency_bucket_counts: list[int] = [0] * (len(_LATENCY_BUCKETS) + 1)
_latency_sum: float = 0.0
_latency_count: int = 0

# Compteurs de cache (par nom de cache)
_cache_hits: dict[str, int] = {}
_cache_misses: dict[str, int] = {}
_cache_miss_reasons: dict[tuple[str, str], int] = {}

# Compteurs d'usage des outils MCP (par nom d'outil)
_tool_calls: dict[str, int] = {}

# Gauge : appels FFBB en vol
_ffbb_inflight: int = 0

_metrics_lock = Lock()


# ---------------------------------------------------------------------------
# Enregistrement
# ---------------------------------------------------------------------------


def record_call(latency: float, is_error: bool) -> None:
    """Enregistre un appel API FFBB (latence + statut)."""
    global _calls_success, _calls_error, _latency_sum, _latency_count
    with _metrics_lock:
        if is_error:
            _calls_error += 1
        else:
            _calls_success += 1
        _latency_sum += latency
        _latency_count += 1
        # bisect_left : O(log n) — équivalent exact de « premier bucket où latency <= bound »
        i = bisect.bisect_left(_LATENCY_BUCKETS, latency)
        if i < len(_LATENCY_BUCKETS):
            _latency_bucket_counts[i] += 1
        # +Inf bucket : toujours incrémenté
        _latency_bucket_counts[len(_LATENCY_BUCKETS)] += 1


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


def record_cache_miss(cache_name: str, reason: str = "not_found") -> None:
    """Enregistre un miss de cache.

    À appeler uniquement depuis _cache_get (pas depuis _cache_set) pour
    éviter le double-comptage.
    """
    with _metrics_lock:
        _cache_misses[cache_name] = _cache_misses.get(cache_name, 0) + 1
        key = (cache_name, reason)
        _cache_miss_reasons[key] = _cache_miss_reasons.get(key, 0) + 1


def record_tool_call(tool_name: str) -> None:
    """Enregistre un appel d'outil MCP par nom d'outil exposé."""
    with _metrics_lock:
        _tool_calls[tool_name] = _tool_calls.get(tool_name, 0) + 1


def reset_metrics() -> None:
    """Réinitialise les métriques en mémoire (usage tests)."""
    global START_TIME, _calls_success, _calls_error, _latency_sum, _latency_count
    global _ffbb_inflight
    with _metrics_lock:
        START_TIME = time.time()
        _calls_success = 0
        _calls_error = 0
        _latency_sum = 0.0
        _latency_count = 0
        _ffbb_inflight = 0
        for i in range(len(_latency_bucket_counts)):
            _latency_bucket_counts[i] = 0
        _cache_hits.clear()
        _cache_misses.clear()
        _cache_miss_reasons.clear()
        _tool_calls.clear()


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def get_snapshot() -> dict[str, Any]:
    """Retourne un snapshot instantané des métriques (thread-safe).

    Les métriques dérivées (error_rate, avg_latency, hit_ratio) sont
    intentionnellement absentes de l'export Prometheus — calculez-les via
    PromQL (rate(), sum()/sum()). Elles restent disponibles ici pour les
    besoins internes (dashboard, logging).
    """
    with _metrics_lock:
        success = _calls_success
        errors = _calls_error
        lat_sum = _latency_sum
        lat_count = _latency_count
        lat_buckets = list(_latency_bucket_counts)
        inflight = _ffbb_inflight
        hits = dict(_cache_hits)
        misses = dict(_cache_misses)
        miss_reasons = dict(_cache_miss_reasons)
        tool_calls = dict(_tool_calls)

    calls = success + errors
    error_rate = errors / calls if calls > 0 else 0.0
    avg_latency = lat_sum / lat_count if lat_count > 0 else 0.0

    cache_stats: dict[str, dict[str, Any]] = {}
    for name in set(hits) | set(misses):
        h = hits.get(name, 0)
        m = misses.get(name, 0)
        total = h + m
        cache_stats[name] = {
            "hits": h,
            "misses": m,
            "total": total,
            "hit_ratio": h / total if total > 0 else 0.0,
        }

    return {
        "uptime_seconds": time.time() - START_TIME,
        "api_calls_success": success,
        "api_calls_error": errors,
        "api_error_rate": error_rate,
        "api_avg_latency_seconds": avg_latency,
        "api_latency_sum": lat_sum,
        "api_latency_count": lat_count,
        "api_latency_buckets": lat_buckets,
        "api_inflight_requests": inflight,
        "cache": cache_stats,
        "cache_miss_reasons": miss_reasons,
        "tool_calls": tool_calls,
    }


# ---------------------------------------------------------------------------
# Export Prometheus
# ---------------------------------------------------------------------------


def _prom_block(name: str, help_: str, type_: str, *lines: str) -> list[str]:
    """Retourne un bloc Prometheus complet : HELP, TYPE, puis les lignes de valeurs."""
    return [f"# HELP {name} {help_}", f"# TYPE {name} {type_}", *lines, ""]


def generate_prometheus_metrics() -> str:
    """Génère les métriques au format texte Prometheus (exposition standard).

    Conforme aux best practices Prometheus :
    - Pas de ratios précalculés (calculés côté PromQL)
    - Pas de totaux globaux redondants (sum() en PromQL)
    - Latence exposée via histogram (buckets + sum + count)
    - Labels {status} sur api_calls pour corrélation erreurs/succès
    """
    snap = get_snapshot()

    lines: list[str] = (
        _prom_block(
            "ffbb_uptime_seconds",
            "Uptime du serveur en secondes",
            "gauge",
            f"ffbb_uptime_seconds {snap['uptime_seconds']:.2f}",
        )
        + _prom_block(
            "ffbb_api_calls_total",
            "Total des appels vers l'API FFBB",
            "counter",
            f'ffbb_api_calls_total{{status="success"}} {snap["api_calls_success"]}',
            f'ffbb_api_calls_total{{status="error"}} {snap["api_calls_error"]}',
        )
        + [
            "# HELP ffbb_api_latency_seconds Latence des appels API FFBB",
            "# TYPE ffbb_api_latency_seconds histogram",
        ]
    )

    # Buckets cumulatifs
    cumulative = 0
    for i, bound in enumerate(_LATENCY_BUCKETS):
        cumulative += snap["api_latency_buckets"][i]
        lines.append(f'ffbb_api_latency_seconds_bucket{{le="{bound}"}} {cumulative}')
    lines.append(
        f'ffbb_api_latency_seconds_bucket{{le="+Inf"}} {snap["api_latency_count"]}'
    )
    lines += [
        f"ffbb_api_latency_seconds_sum {snap['api_latency_sum']:.4f}",
        f"ffbb_api_latency_seconds_count {snap['api_latency_count']}",
        "",
    ]

    lines += _prom_block(
        "ffbb_api_inflight_requests",
        "Nombre d'appels FFBB en cours",
        "gauge",
        f"ffbb_api_inflight_requests {snap['api_inflight_requests']}",
    )

    cache_stats: dict[str, dict] = snap["cache"]
    if cache_stats:
        lines += _prom_block(
            "ffbb_cache_hits_total",
            "Hits de cache par cache",
            "counter",
            *[
                f'ffbb_cache_hits_total{{cache="{n}"}} {s["hits"]}'
                for n, s in cache_stats.items()
            ],
        ) + _prom_block(
            "ffbb_cache_misses_total",
            "Misses de cache par cache",
            "counter",
            *[
                f'ffbb_cache_misses_total{{cache="{n}"}} {s["misses"]}'
                for n, s in cache_stats.items()
            ],
        )

    cache_miss_reasons: dict[tuple[str, str], int] = snap["cache_miss_reasons"]
    if cache_miss_reasons:
        lines += _prom_block(
            "ffbb_cache_misses_by_reason_total",
            "Misses de cache par cache et raison",
            "counter",
            *[
                f'ffbb_cache_misses_by_reason_total{{cache="{cache}",reason="{reason}"}} {count}'
                for (cache, reason), count in cache_miss_reasons.items()
            ],
        )

    tool_calls: dict[str, int] = snap.get("tool_calls", {})
    if tool_calls:
        lines += _prom_block(
            "ffbb_mcp_tool_calls_total",
            "Total des appels d'outils MCP par nom d'outil",
            "counter",
            *[
                f'ffbb_mcp_tool_calls_total{{tool="{name}"}} {count}'
                for name, count in sorted(tool_calls.items())
            ],
        )

    return "\n".join(lines) + "\n"


def summarize_health(snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Construit un résumé compact de santé à partir d'un snapshot métriques."""
    snap = dict(snapshot) if snapshot is not None else get_snapshot()
    cache = snap.get("cache", {})
    cache_hits = sum(stat["hits"] for stat in cache.values())
    cache_misses = sum(stat["misses"] for stat in cache.values())
    cache_total = cache_hits + cache_misses
    api_calls_total = snap["api_calls_success"] + snap["api_calls_error"]
    api_errors_total = snap["api_calls_error"]
    inflight = snap["api_inflight_requests"]

    if api_errors_total:
        status = "degraded"
    elif inflight:
        status = "busy"
    else:
        status = "ok"

    return {
        "status": status,
        "api_calls_total": api_calls_total,
        "api_calls_success": snap["api_calls_success"],
        "api_errors_total": api_errors_total,
        "api_error_rate": snap["api_error_rate"],
        "api_avg_latency_seconds": snap["api_avg_latency_seconds"],
        "api_inflight_requests": inflight,
        "cache_hits_total": cache_hits,
        "cache_misses_total": cache_misses,
        "cache_hit_ratio_global": cache_hits / cache_total if cache_total else 0.0,
    }
