"""Tests unitaires des services FFBB (avec mocks, sans appel réseau)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ffbb_mcp.services import (
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    get_calendrier_club_service,
    get_competition_service,
    get_organisme_service,
    get_saisons_service,
    _cache_lives,
    _cache_search,
    _cache_detail,
)

@pytest.fixture(autouse=True)
def clear_caches():
    _cache_lives.clear()
    _cache_search.clear()
    _cache_detail.clear()
    yield

# ... (TestHandleApiError and TestGetLivesService remain same)

# ---------------------------------------------------------------------------
# Tests — get_saisons_service
# ---------------------------------------------------------------------------


class TestGetSaisonsService:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_saisons(
        self, patch_get_client, mock_client
    ):
        mock_client.get_saisons_async = AsyncMock(return_value=[])
        result = await get_saisons_service(active_only=True)
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

        result_active = await get_saisons_service(active_only=True)
        assert len(result_active) == 1
        assert result_active[0]["nom"] == "2024-2025"


# ---------------------------------------------------------------------------
# Tests — get_competition_service
# ---------------------------------------------------------------------------


class TestGetCompetitionService:
    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_not_found(
        self, patch_get_client, mock_client
    ):
        mock_client.get_competition_async = AsyncMock(return_value=None)
        result = await get_competition_service(competition_id=99999)
        assert result == {}


# ---------------------------------------------------------------------------
# Tests — get_organisme_service
# ---------------------------------------------------------------------------


class TestGetOrganismeService:
    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_not_found(
        self, patch_get_client, mock_client
    ):
        mock_client.get_organisme_async = AsyncMock(return_value=None)
        result = await get_organisme_service(organisme_id=99999)
        assert result == {}


# ---------------------------------------------------------------------------
# Tests — ffbb_equipes_club_service
# ---------------------------------------------------------------------------


class TestEquipesClubService:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_org(self, patch_get_client, mock_client):
        mock_client.get_organisme_async = AsyncMock(return_value=None)
        result = await ffbb_equipes_club_service(organisme_id=123)
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
                        "idCompetition": {"nom": "U11M", "id": "comp1"},
                        "idPoule": {"id": "poule1"},
                    }
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)
        result = await ffbb_equipes_club_service(organisme_id=123)
        assert len(result) == 1
        assert result[0]["nom_equipe"] == "Club Test"
        assert result[0]["competition"] == "U11M"

    @pytest.mark.asyncio
    async def test_filtre_works(self, patch_get_client, mock_client):
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "nom": "Club",
                "engagements": [
                    {"idCompetition": {"nom": "U11M"}, "idPoule": {"id": "p1"}},
                    {"idCompetition": {"nom": "U13F"}, "idPoule": {"id": "p2"}},
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        # Test filtre U11
        result = await ffbb_equipes_club_service(organisme_id=1, filtre="U11")
        assert len(result) == 1
        assert result[0]["competition"] == "U11M"


# ---------------------------------------------------------------------------
# Tests — ffbb_get_classement_service
# ---------------------------------------------------------------------------


class TestGetClassementService:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_poule(self, patch_get_client, mock_client):
        mock_client.get_poule_async = AsyncMock(return_value=None)
        result = await ffbb_get_classement_service(poule_id=123)
        assert result == []


# ---------------------------------------------------------------------------
# Tests — get_calendrier_club_service
# ---------------------------------------------------------------------------


class TestCalendrierClubService:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_results(self, patch_get_client, mock_client):
        mock_client.search_rencontres_async = AsyncMock(return_value=None)
        result = await get_calendrier_club_service(club_name="Club Inexistant")
        assert result == []

    @pytest.mark.asyncio
    async def test_resolves_id_to_name(self, patch_get_client, mock_client):
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(return_value={"nom": "BASKET CLUB"})
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        mock_client.search_rencontres_async = AsyncMock(return_value=None)

        await get_calendrier_club_service(organisme_id=123)

        # Doit avoir appelé get_organisme puis search_rencontres avec le nom résolu
        mock_client.get_organisme_async.assert_called_with(organisme_id=123)
        mock_client.search_rencontres_async.assert_called_with("BASKET CLUB")
