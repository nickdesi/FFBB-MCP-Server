from ffbb_mcp.metrics import summarize_health


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
