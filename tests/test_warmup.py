"""Tests unitaires pour le service de préchauffage (warmup) du cache."""

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from ffbb_mcp.app_factory import create_app
from ffbb_mcp.server import mcp
from ffbb_mcp.services.warmup import warmup_cache_service


@pytest.fixture
def client():
    app = create_app(mcp, allowed_origins=["*"])
    return TestClient(app)


class TestWarmupService:
    @pytest.mark.asyncio
    @patch("ffbb_mcp.services.warmup.get_organisme_service", new_callable=AsyncMock)
    @patch(
        "ffbb_mcp.services.warmup.get_calendrier_club_service", new_callable=AsyncMock
    )
    @patch("ffbb_mcp.services.warmup.ffbb_equipes_club_service", new_callable=AsyncMock)
    @patch("ffbb_mcp.services.warmup.get_poule_service", new_callable=AsyncMock)
    async def test_warmup_success_with_organisme_ids(
        self,
        mock_get_poule,
        mock_ffbb_equipes,
        mock_get_calendrier,
        mock_get_organisme,
    ):
        # Mocks
        mock_get_organisme.return_value = {"id": "123", "nom": "Club A"}
        mock_get_calendrier.return_value = [{"id": "m1"}]
        mock_ffbb_equipes.return_value = [
            {"engagement_id": "eng1", "poule_id": "poule_1", "nom_equipe": "Club A"}
        ]
        mock_get_poule.return_value = {"id": "poule_1"}

        result = await warmup_cache_service(organisme_ids=["123"])

        # Assertions sur les résultats
        assert result["status"] == "completed"
        assert result["details"]["organismes_demandes"] == 1
        assert result["details"]["organismes_prechauffes"] == 1
        assert result["details"]["calendriers_prechauffes"] == 1
        assert result["details"]["poules_detectees"] == 1
        assert result["details"]["poules_prechauffees"] == 1

        # Vérifier que les fonctions mockées ont été appelées
        mock_get_organisme.assert_awaited_once_with("123")
        mock_get_calendrier.assert_awaited_once_with(organisme_id="123")
        mock_ffbb_equipes.assert_awaited_once_with(organisme_id="123")
        mock_get_poule.assert_awaited_once_with("poule_1")

    @pytest.mark.asyncio
    async def test_warmup_skipped_when_no_organismes(self):
        result = await warmup_cache_service(organisme_ids=[])
        assert result["status"] == "skipped"
        assert "Aucun organisme à préchauffer" in result["message"]

    @pytest.mark.asyncio
    @patch("ffbb_mcp.services.warmup.get_organisme_service", new_callable=AsyncMock)
    @patch(
        "ffbb_mcp.services.warmup.get_calendrier_club_service", new_callable=AsyncMock
    )
    @patch("ffbb_mcp.services.warmup.ffbb_equipes_club_service", new_callable=AsyncMock)
    @patch("ffbb_mcp.services.warmup.get_poule_service", new_callable=AsyncMock)
    async def test_warmup_with_env_var(
        self,
        mock_get_poule,
        mock_ffbb_equipes,
        mock_get_calendrier,
        mock_get_organisme,
        monkeypatch,
    ):
        monkeypatch.setenv("FFBB_WARMUP_ORGANISMES", "123, 456")

        mock_get_organisme.return_value = {"id": "x"}
        mock_get_calendrier.return_value = []
        mock_ffbb_equipes.return_value = []

        result = await warmup_cache_service(organisme_ids=None)

        assert result["status"] == "completed"
        assert result["details"]["organismes_demandes"] == 2
        assert mock_get_organisme.await_count == 2
        mock_get_organisme.assert_any_await("123")
        mock_get_organisme.assert_any_await("456")


class TestWarmupRoutes:
    def test_get_warmup_info(self, client):
        response = client.get("/cache/warmup")
        assert response.status_code == 200
        data = response.json()
        assert data["endpoint"] == "/cache/warmup"
        assert "POST" in data["methods"]
        assert "FFBB_WARMUP_ORGANISMES" in data["env_var_config"]

    @patch("ffbb_mcp.services.warmup.warmup_cache_service", new_callable=AsyncMock)
    def test_post_warmup_sync(self, mock_warmup, client):
        mock_warmup.return_value = {"status": "completed", "details": {}}

        response = client.post(
            "/cache/warmup", json={"organisme_ids": ["123"], "sync": True}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        mock_warmup.assert_awaited_once_with(organisme_ids=["123"])

    @patch("ffbb_mcp.services.warmup.warmup_cache_service", new_callable=AsyncMock)
    def test_post_warmup_async(self, mock_warmup, client):
        response = client.post(
            "/cache/warmup", json={"organisme_ids": ["123"], "sync": False}
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "tâche de fond" in data["message"]
