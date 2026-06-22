from ffbb_mcp.metrics import (
    generate_prometheus_metrics,
    get_snapshot,
    record_tool_call,
    reset_metrics,
    summarize_health,
)


def test_summarize_health_ok_with_empty_metrics():
    summary = summarize_health(
        {
            "api_calls_success": 0,
            "api_calls_error": 0,
            "api_error_rate": 0.0,
            "api_avg_latency_seconds": 0.0,
            "api_inflight_requests": 0,
            "cache": {},
        }
    )

    assert summary == {
        "status": "ok",
        "api_calls_total": 0,
        "api_calls_success": 0,
        "api_errors_total": 0,
        "api_error_rate": 0.0,
        "api_avg_latency_seconds": 0.0,
        "api_inflight_requests": 0,
        "cache_hits_total": 0,
        "cache_misses_total": 0,
        "cache_hit_ratio_global": 0.0,
    }


def test_summarize_health_busy_without_errors():
    summary = summarize_health(
        {
            "api_calls_success": 2,
            "api_calls_error": 0,
            "api_error_rate": 0.0,
            "api_avg_latency_seconds": 0.25,
            "api_inflight_requests": 1,
            "cache": {
                "search": {"hits": 3, "misses": 1},
                "detail": {"hits": 1, "misses": 0},
            },
        }
    )

    assert summary["status"] == "busy"
    assert summary["api_calls_total"] == 2
    assert summary["cache_hits_total"] == 4
    assert summary["cache_misses_total"] == 1
    assert summary["cache_hit_ratio_global"] == 0.8


def test_summarize_health_degraded_when_errors():
    summary = summarize_health(
        {
            "api_calls_success": 3,
            "api_calls_error": 1,
            "api_error_rate": 0.25,
            "api_avg_latency_seconds": 1.0,
            "api_inflight_requests": 1,
            "cache": {},
        }
    )

    assert summary["status"] == "degraded"
    assert summary["api_calls_total"] == 4
    assert summary["api_errors_total"] == 1


def test_tool_calls_present_in_snapshot_and_prometheus():
    reset_metrics()

    record_tool_call("ffbb_version")
    record_tool_call("ffbb_version")
    record_tool_call("ffbb_search")

    snapshot = get_snapshot()
    assert snapshot["tool_calls"] == {"ffbb_version": 2, "ffbb_search": 1}

    prom = generate_prometheus_metrics()
    assert "ffbb_mcp_tool_calls_total" in prom
    assert 'ffbb_mcp_tool_calls_total{tool="ffbb_version"} 2' in prom
    assert 'ffbb_mcp_tool_calls_total{tool="ffbb_search"} 1' in prom


def test_metrics_persistence(tmp_path, monkeypatch):
    from ffbb_mcp.metrics import (
        _get_metrics_file,
        _save_metrics_to_disk,
        get_snapshot,
        load_metrics,
        record_tool_call,
        reset_metrics,
    )

    # Configurer le répertoire de données vers le dossier temporaire
    monkeypatch.setenv("FFBB_DATA_DIR", str(tmp_path))

    reset_metrics()
    record_tool_call("ffbb_resolve_team")
    record_tool_call("ffbb_resolve_team")
    record_tool_call("ffbb_next_match")

    # Forcer la sauvegarde immédiate sur le disque
    _save_metrics_to_disk()

    metrics_file = _get_metrics_file()
    assert metrics_file.exists()

    # Réinitialiser en mémoire
    reset_metrics()
    snapshot_empty = get_snapshot()
    assert "ffbb_resolve_team" not in snapshot_empty["tool_calls"]

    # Charger depuis le disque
    load_metrics()

    snapshot_restored = get_snapshot()
    assert snapshot_restored["tool_calls"]["ffbb_resolve_team"] == 2
    assert snapshot_restored["tool_calls"]["ffbb_next_match"] == 1
