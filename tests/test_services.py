"""Tests unitaires des services FFBB (avec mocks, sans appel réseau)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.shared.exceptions import McpError

from ffbb_mcp.schemas import (
    CalendrierClubInput,
    CompetitionIdInput,
    OrganismeIdInput,
    PouleIdInput,
    SaisonsInput,
)
from ffbb_mcp.services import (
    _handle_api_error,
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    get_calendrier_club_service,
    get_competition_service,
    get_lives_service,
    get_organisme_service,
    get_saisons_service,
)

# ---------------------------------------------------------------------------
# Tests — _handle_api_error
# ---------------------------------------------------------------------------

class TestHandleApiError:
    """Tests du formateur d'erreurs API."""

    def test_mcp_error(self):
        err = McpError(error=MagicMock(message="Existing error"))
        result = _handle_api_error(err)
        assert result == err

    def test_generic_error(self):
        err = ValueError("test error")
        msg_err = _handle_api_error(err)
        assert isinstance(msg_err, McpError)
        assert "test error" in msg_err.error.message

# ---------------------------------------------------------------------------
# Tests — get_lives_service
# ---------------------------------------------------------------------------

class TestGetLivesService:

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_lives(self, patch_get_client, mock_client):
        mock_client.get_lives_async = AsyncMock(return_value=[])
        result = await get_lives_service()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_error_on_api_down(self, patch_get_client, mock_client):
        mock_client.get_lives_async = AsyncMock(side_effect=Exception("API down"))
        with pytest.raises(McpError):
            await get_lives_service()


# ---------------------------------------------------------------------------
# Tests — get_saisons_service
# ---------------------------------------------------------------------------

class TestGetSaisonsService:

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_saisons(self, patch_get_client, mock_client):
        mock_client.get_saisons_async = AsyncMock(return_value=[])
        params = SaisonsInput(active_only=True)
        result = await get_saisons_service(params)
        assert result == []

    @pytest.mark.asyncio
    async def test_active_filter(self, patch_get_client, mock_client):
        def mock_get_saisons(active_only=False):
            data = [
                {"id": 1, "nom": "2023-2024", "actif": False},
                {"id": 2, "nom": "2024-2025", "actif": True},
            ]
            if active_only:
                return [d for d in data if d.get("actif")]
            return data
            
        mock_client.get_saisons_async = AsyncMock(side_effect=mock_get_saisons)
        
        result_active = await get_saisons_service(SaisonsInput(active_only=True))
        assert len(result_active) == 1
        assert result_active[0]["nom"] == "2024-2025"
        mock_client.get_saisons_async.assert_called_with(active_only=True)

# ---------------------------------------------------------------------------
# Tests — get_competition_service
# ---------------------------------------------------------------------------

class TestGetCompetitionService:

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_not_found(self, patch_get_client, mock_client):
        mock_client.get_competition_async = AsyncMock(return_value=None)
        params = CompetitionIdInput(competition_id=99999)
        result = await get_competition_service(params)
        assert result == {}


# ---------------------------------------------------------------------------
# Tests — get_organisme_service
# ---------------------------------------------------------------------------

class TestGetOrganismeService:

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_not_found(self, patch_get_client, mock_client):
        mock_client.get_organisme_async = AsyncMock(return_value=None)
        params = OrganismeIdInput(organisme_id=99999)
        result = await get_organisme_service(params)
        assert result == {}


# ---------------------------------------------------------------------------
# Tests — ffbb_equipes_club_service
# ---------------------------------------------------------------------------

class TestEquipesClubService:

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_org(self, patch_get_client, mock_client):
        mock_client.get_organisme_async = AsyncMock(return_value=None)
        params = OrganismeIdInput(organisme_id=123)
        result = await ffbb_equipes_club_service(params)
        assert result == []

    @pytest.mark.asyncio
    async def test_extracts_engagements_flattened(self, patch_get_client, mock_client):
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "nom": "Club Test",
                "engagements": [
                    {
                        "id": "eng1",
                        "idCompetition": {
                            "nom": "U11M",
                            "id": "comp1",
                            "code": "C1",
                            "sexe": "M",
                        },
                        "idPoule": {"id": "poule1"},
                    }
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)
        params = OrganismeIdInput(organisme_id=123)
        result = await ffbb_equipes_club_service(params)
        assert len(result) == 1
        assert result[0]["nom_equipe"] == "Club Test"
        assert result[0]["competition"] == "U11M"
        assert result[0]["poule_id"] == "poule1"
        assert result[0]["sexe"] == "M"


# ---------------------------------------------------------------------------
# Tests — ffbb_get_classement_service
# ---------------------------------------------------------------------------

class TestGetClassementService:

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_poule(self, patch_get_client, mock_client):
        mock_client.get_poule_async = AsyncMock(return_value=None)
        params = PouleIdInput(poule_id=123)
        result = await ffbb_get_classement_service(params)
        assert result == []

    @pytest.mark.asyncio
    async def test_extracts_classement_plural_and_flattened(self, patch_get_client, mock_client):
        poule_mock = MagicMock()
        poule_mock.model_dump = MagicMock(
            return_value={
                "classements": [
                    {
                        "position": 1,
                        "points": 10,
                        "id_engagement": {"nom": "Team A", "numero_equipe": "1"},
                    }
                ]
            }
        )
        mock_client.get_poule_async = AsyncMock(return_value=poule_mock)
        params = PouleIdInput(poule_id=123)
        result = await ffbb_get_classement_service(params)
        assert len(result) == 1
        assert result[0]["equipe"] == "Team A"
        assert result[0]["numero_equipe"] == "1"
        assert result[0]["position"] == 1


# ---------------------------------------------------------------------------
# Tests — get_calendrier_club_service
# ---------------------------------------------------------------------------

class TestCalendrierClubService:

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_results(self, patch_get_client, mock_client):
        mock_client.search_rencontres_async = AsyncMock(return_value=None)
        params = CalendrierClubInput(club_name="Club Inexistant")
        result = await get_calendrier_club_service(params)
        assert result == []

    @pytest.mark.asyncio
    async def test_combines_club_and_categorie(self, patch_get_client, mock_client):
        hits_mock = MagicMock()
        hit1 = MagicMock()
        hit1.model_dump = MagicMock(
            return_value={
                "id": "m1",
                "date_rencontre": "2025-03-01",
                "nom_equipe1": "ASVEL U13M",
                "nom_equipe2": "Vichy U13M",
            }
        )
        hits_mock.hits = [hit1]
        mock_client.search_rencontres_async = AsyncMock(return_value=hits_mock)

        params = CalendrierClubInput(club_name="ASVEL", categorie="U13M")
        result = await get_calendrier_club_service(params)
        
        assert len(result) == 1
        assert result[0]["nom_equipe1"] == "ASVEL U13M"
        assert result[0]["date"] == "2025-03-01"

        call_args = mock_client.search_rencontres_async.call_args
        assert "ASVEL U13M" in str(call_args)
