"""Tests unitaires pour le module de benchmark de performance (benchmark.py)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp._state import state
from ffbb_mcp.benchmark import (
    _evict_runtime_caches_for_benchmark,
    get_benchmark_trends,
    reset_benchmark,
    run_benchmark,
)


@pytest.fixture
def temp_benchmark_file(tmp_path):
    """Fixture isolant le fichier de résultats du benchmark."""
    test_file = tmp_path / "test_benchmark_results.json"
    with (
        patch("ffbb_mcp.benchmark._BENCHMARK_FILE", test_file),
        patch("ffbb_mcp.benchmark._BENCHMARK_DIR", tmp_path),
    ):
        reset_benchmark()  # Partir d'un historique vide
        yield test_file


def test_evict_runtime_caches_for_benchmark():
    """Vérifie que l'éviction vide effectivement tous les caches du service layer."""
    from cachetools import TLRUCache, TTLCache

    # Remplir temporairement des caches simulés
    state.cache_search = TTLCache(maxsize=10, ttl=60)
    state.cache_search["key"] = "val"

    state.cache_bilan = TLRUCache(maxsize=10, ttu=lambda k, v, t: t + 60)
    state.cache_bilan["key"] = "val"

    assert len(state.cache_search) > 0
    assert len(state.cache_bilan) > 0

    _evict_runtime_caches_for_benchmark()

    assert len(state.cache_search) == 0
    assert len(state.cache_bilan) == 0


@pytest.mark.asyncio
async def test_run_benchmark_success(temp_benchmark_file):
    """Vérifie le déroulement d'un run de benchmark réussi et sa persistance."""
    mock_orgs = [{"id": "12345", "nom": "Stade Clermontois"}]
    mock_equipes = [{"id": "E1", "nom": "U11M1"}]
    mock_bilan = {"success": True, "details": []}

    with (
        patch(
            "ffbb_mcp.benchmark.search_organismes_service",
            new_callable=AsyncMock,
            return_value=mock_orgs,
        ) as mock_search,
        patch(
            "ffbb_mcp.benchmark.ffbb_equipes_club_service",
            new_callable=AsyncMock,
            return_value=mock_equipes,
        ) as mock_get_eq,
        patch(
            "ffbb_mcp.benchmark.ffbb_bilan_service",
            new_callable=AsyncMock,
            return_value=mock_bilan,
        ) as mock_get_bilan,
    ):
        run = await run_benchmark()

        assert run["success"] is True
        assert run["error"] is None
        assert len(run["steps"]) == 3
        assert run["total_ms"] >= 0

        # Vérifier les appels
        mock_search.assert_called_once_with(nom="Stade Clermontois")
        mock_get_eq.assert_called_once_with(organisme_id="12345", filtre="U11M")
        mock_get_bilan.assert_called_once_with(
            organisme_id="12345", categorie="U11M", force_refresh=True
        )

        # Vérifier la persistance dans le fichier
        assert temp_benchmark_file.exists()
        saved = json.loads(temp_benchmark_file.read_text(encoding="utf-8"))
        assert len(saved["runs"]) == 1
        assert saved["runs"][0]["success"] is True


@pytest.mark.asyncio
async def test_run_benchmark_failure(temp_benchmark_file):
    """Vérifie la capture des exceptions d'une étape de benchmark en échec."""
    with patch(
        "ffbb_mcp.benchmark.search_organismes_service",
        new_callable=AsyncMock,
        side_effect=ValueError("API connection failed"),
    ):
        run = await run_benchmark()

        assert run["success"] is False
        assert "API connection failed" in run["error"]
        assert len(run["steps"]) == 1
        assert run["steps"][0]["error"] == "API connection failed"

        # Vérifier que le run en échec est quand même historisé
        saved = json.loads(temp_benchmark_file.read_text(encoding="utf-8"))
        assert len(saved["runs"]) == 1
        assert saved["runs"][0]["success"] is False


def test_get_benchmark_trends_calculation(temp_benchmark_file):
    """Vérifie les calculs de statistiques de tendances et de taux de succès."""
    # Historique vide
    trends_empty = get_benchmark_trends()
    assert trends_empty["runs"] == []
    assert trends_empty["latest"] is None
    assert trends_empty["success_rate"] == 100.0

    # Injecter des faux runs
    mock_runs = [
        {"success": True, "total_ms": 100.0, "timestamp": "2026-05-20T10:00:00Z"},
        {"success": False, "total_ms": 50.0, "timestamp": "2026-05-20T10:05:00Z"},
        {"success": True, "total_ms": 120.0, "timestamp": "2026-05-20T10:10:00Z"},
    ]
    temp_benchmark_file.write_text(json.dumps({"runs": mock_runs}), encoding="utf-8")

    trends = get_benchmark_trends()
    assert trends["total_runs"] == 3
    # 2 réussis sur 3 -> 66.7%
    assert trends["success_rate"] == 66.7
    # Moyenne des runs réussis: (100 + 120) / 2 = 110.0
    assert trends["average_ms"] == 110.0
    assert trends["latest"]["timestamp"] == "2026-05-20T10:10:00Z"


def test_get_benchmark_trends_direction(temp_benchmark_file):
    """Vérifie la détection de direction (stable, amélioration, dégradation)."""
    # 1. Stable
    runs_stable = [
        {"success": True, "total_ms": 100.0},
        {"success": True, "total_ms": 102.0},
        {"success": True, "total_ms": 99.0},
    ]
    temp_benchmark_file.write_text(json.dumps({"runs": runs_stable}), encoding="utf-8")
    assert get_benchmark_trends()["direction"] == "stable"

    # 2. Amélioration (temps en baisse)
    runs_improving = [
        {"success": True, "total_ms": 100.0},
        {"success": True, "total_ms": 80.0},
        {"success": True, "total_ms": 70.0},
    ]
    temp_benchmark_file.write_text(
        json.dumps({"runs": runs_improving}), encoding="utf-8"
    )
    assert get_benchmark_trends()["direction"] == "improving"

    # 3. Dégradation (temps en hausse)
    runs_degrading = [
        {"success": True, "total_ms": 100.0},
        {"success": True, "total_ms": 120.0},
        {"success": True, "total_ms": 130.0},
    ]
    temp_benchmark_file.write_text(
        json.dumps({"runs": runs_degrading}), encoding="utf-8"
    )
    assert get_benchmark_trends()["direction"] == "degrading"
