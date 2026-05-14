"""Tests du dashboard HTML."""

from ffbb_mcp.dashboard import _build_dashboard_html


def test_dashboard_html_renders_empty_cache(monkeypatch):
    monkeypatch.setattr(
        "ffbb_mcp.dashboard.get_snapshot",
        lambda: {
            "uptime_seconds": 65,
            "api_calls_success": 0,
            "api_calls_error": 0,
            "api_error_rate": 0.0,
            "api_avg_latency_seconds": 0.0,
            "api_inflight_requests": 0,
            "cache": {},
            "tool_calls": {},
        },
    )

    html = _build_dashboard_html()

    assert "HEALTHY" in html
    assert "1m" not in html
    assert "0j 00:01:05" in html
    assert "Aucune donnee de cache" in html
    assert "Aucun appel outil MCP observe" in html
    assert "FFBB MCP DASHBOARD" in html


def test_dashboard_html_renders_degraded_cache_rows(monkeypatch):
    monkeypatch.setattr(
        "ffbb_mcp.dashboard.get_snapshot",
        lambda: {
            "uptime_seconds": 90061,
            "api_calls_success": 3,
            "api_calls_error": 1,
            "api_error_rate": 0.25,
            "api_avg_latency_seconds": 0.123,
            "api_inflight_requests": 2,
            "cache": {
                "hot": {"hits": 8, "misses": 2, "total": 10, "hit_ratio": 0.8},
                "cold": {"hits": 1, "misses": 3, "total": 4, "hit_ratio": 0.25},
            },
            "tool_calls": {
                "ffbb_search": 7,
                "ffbb_get": 5,
                "ffbb_team_summary": 3,
            },
        },
    )

    html = _build_dashboard_html()

    assert "DEGRADED" in html
    assert "1j 01:01:01" in html
    assert "taux d'echec 25.0%" in html
    assert "123.0" in html
    assert "class='cache-name'>hot" in html
    assert "class='cache-name'>cold" in html
    assert "80.0%" in html
    assert "25.0%" in html
    assert "En cours" in html
    assert "Usage des Outils MCP" in html
    assert "Calls Core" in html
    assert "Calls Legacy" in html
    assert "class='cache-name'>ffbb_search" in html
    assert "class='cache-name'>ffbb_team_summary" in html
    assert ">CORE<" in html
    assert ">LEGACY<" in html
