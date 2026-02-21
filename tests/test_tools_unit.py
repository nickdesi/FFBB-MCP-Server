"""Tests unitaires des outils MCP FFBB (avec mocks, sans appel réseau)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from ffbb_mcp.server import (
    _handle_api_error,
    ffbb_calendrier_club,
    ffbb_equipes_club,
    ffbb_get_classement,
    ffbb_get_competition,
    ffbb_get_lives,
    ffbb_get_organisme,
    ffbb_get_saisons,
)


# ---------------------------------------------------------------------------
# Tests — _handle_api_error
# ---------------------------------------------------------------------------


class TestHandleApiError:
    """Tests du formateur d'erreurs API."""

    def test_404_error(self):
        response = MagicMock(status_code=404)
        err = httpx.HTTPStatusError("not found", request=MagicMock(), response=response)
        msg = _handle_api_error(err)
        assert "introuvable" in msg.lower()

    def test_403_error(self):
        response = MagicMock(status_code=403)
        err = httpx.HTTPStatusError("forbidden", request=MagicMock(), response=response)
        msg = _handle_api_error(err)
        assert "refusé" in msg.lower()

    def test_429_error(self):
        response = MagicMock(status_code=429)
        err = httpx.HTTPStatusError("too many", request=MagicMock(), response=response)
        msg = _handle_api_error(err)
        assert "limite" in msg.lower()

    def test_timeout_error(self):
        err = httpx.TimeoutException("timeout")
        msg = _handle_api_error(err)
        assert "délai" in msg.lower() or "attente" in msg.lower()

    def test_generic_error(self):
        err = ValueError("test error")
        msg = _handle_api_error(err)
        assert "ValueError" in msg
        assert "test error" in msg


# ---------------------------------------------------------------------------
# Tests — ffbb_get_lives
# ---------------------------------------------------------------------------


class TestGetLives:
    """Tests de l'outil ffbb_get_lives."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_lives(self, mock_ctx, mock_client):
        mock_client.get_lives_async = AsyncMock(return_value=[])
        result = await ffbb_get_lives(mock_ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_error(self, mock_ctx, mock_client):
        mock_client.get_lives_async = AsyncMock(side_effect=Exception("API down"))
        result = await ffbb_get_lives(mock_ctx)
        assert result == []


# ---------------------------------------------------------------------------
# Tests — ffbb_get_saisons
# ---------------------------------------------------------------------------


class TestGetSaisons:
    """Tests de l'outil ffbb_get_saisons."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_saisons(self, mock_ctx, mock_client):
        from ffbb_mcp.server import SaisonsInput

        mock_client.get_saisons_async = AsyncMock(return_value=None)
        params = SaisonsInput(active_only=True)
        result = await ffbb_get_saisons(params, mock_ctx)
        assert result == []


# ---------------------------------------------------------------------------
# Tests — ffbb_get_competition
# ---------------------------------------------------------------------------


class TestGetCompetition:
    """Tests de l'outil ffbb_get_competition."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_not_found(self, mock_ctx, mock_client):
        from ffbb_mcp.server import CompetitionIdInput

        mock_client.get_competition_async = AsyncMock(return_value=None)
        params = CompetitionIdInput(competition_id=99999)
        result = await ffbb_get_competition(params, mock_ctx)
        assert result == {}


# ---------------------------------------------------------------------------
# Tests — ffbb_get_organisme
# ---------------------------------------------------------------------------


class TestGetOrganisme:
    """Tests de l'outil ffbb_get_organisme."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_not_found(self, mock_ctx, mock_client):
        from ffbb_mcp.server import OrganismeIdInput

        mock_client.get_organisme_async = AsyncMock(return_value=None)
        params = OrganismeIdInput(organisme_id=99999)
        result = await ffbb_get_organisme(params, mock_ctx)
        assert result == {}


# ---------------------------------------------------------------------------
# Tests — ffbb_equipes_club (nouveau)
# ---------------------------------------------------------------------------


class TestEquipesClub:
    """Tests de l'outil ffbb_equipes_club."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_org(self, mock_ctx, mock_client):
        from ffbb_mcp.server import OrganismeIdInput

        mock_client.get_organisme_async = AsyncMock(return_value=None)
        params = OrganismeIdInput(organisme_id=123)
        result = await ffbb_equipes_club(params, mock_ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_extracts_engagements(self, mock_ctx, mock_client):
        from ffbb_mcp.server import OrganismeIdInput

        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "nom": "Club Test",
                "engagements": [
                    {"competition": "U11M", "poule_id": 1},
                    {"competition": "U13F", "poule_id": 2},
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)
        params = OrganismeIdInput(organisme_id=123)
        result = await ffbb_equipes_club(params, mock_ctx)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests — ffbb_get_classement (nouveau)
# ---------------------------------------------------------------------------


class TestGetClassement:
    """Tests de l'outil ffbb_get_classement."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_poule(self, mock_ctx, mock_client):
        from ffbb_mcp.server import PouleIdInput

        mock_client.get_poule_async = AsyncMock(return_value=None)
        params = PouleIdInput(poule_id=123)
        result = await ffbb_get_classement(params, mock_ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_extracts_classement(self, mock_ctx, mock_client):
        from ffbb_mcp.server import PouleIdInput

        poule_mock = MagicMock()
        poule_mock.model_dump = MagicMock(
            return_value={
                "nom": "Poule A",
                "classement": [
                    {"position": 1, "equipe": "Team A", "points": 10},
                    {"position": 2, "equipe": "Team B", "points": 8},
                ],
                "rencontres": [],
            }
        )
        mock_client.get_poule_async = AsyncMock(return_value=poule_mock)
        params = PouleIdInput(poule_id=123)
        result = await ffbb_get_classement(params, mock_ctx)
        assert len(result) == 2
        assert result[0]["position"] == 1


# ---------------------------------------------------------------------------
# Tests — ffbb_calendrier_club (nouveau)
# ---------------------------------------------------------------------------


class TestCalendrierClub:
    """Tests de l'outil ffbb_calendrier_club."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_results(self, mock_ctx, mock_client):
        from ffbb_mcp.server import CalendrierClubInput

        mock_client.search_rencontres_async = AsyncMock(return_value=None)
        params = CalendrierClubInput(club_name="Club Inexistant")
        result = await ffbb_calendrier_club(params, mock_ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_combines_club_and_categorie(self, mock_ctx, mock_client):
        from ffbb_mcp.server import CalendrierClubInput

        hits_mock = MagicMock()
        hit1 = MagicMock()
        hit1.model_dump = MagicMock(return_value={"equipe1": "ASVEL U13M", "date": "2025-03-01"})
        hits_mock.hits = [hit1]
        mock_client.search_rencontres_async = AsyncMock(return_value=hits_mock)

        params = CalendrierClubInput(club_name="ASVEL", categorie="U13M")
        result = await ffbb_calendrier_club(params, mock_ctx)
        assert len(result) == 1

        # Vérifier que la recherche combine club + catégorie
        call_args = mock_client.search_rencontres_async.call_args
        assert "ASVEL U13M" in str(call_args)
