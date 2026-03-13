"""Module de tracking des métriques du serveur et des appels FFBB."""

import time
from threading import Lock

START_TIME = time.time()
total_calls = 0
error_calls = 0
total_latency = 0.0
_metrics_lock = Lock()


def record_call(latency: float, is_error: bool) -> None:
    """Enregistre un appel API."""
    global total_calls, error_calls, total_latency
    with _metrics_lock:
        total_calls += 1
        total_latency += latency
        if is_error:
            error_calls += 1


def generate_prometheus_metrics() -> str:
    """Génère les métriques au format texte (compatible Prometheus/Coolify)."""
    uptime = time.time() - START_TIME
    with _metrics_lock:
        calls = total_calls
        errors = error_calls
        latency_total = total_latency

    error_rate = (errors / calls) if calls > 0 else 0.0
    avg_latency = (latency_total / calls) if calls > 0 else 0.0

    lines = [
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
    ]
    return "\n".join(lines) + "\n"
