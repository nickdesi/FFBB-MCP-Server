"""Tests unitaires des services FFBB (avec mocks, sans appel réseau)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from ffbb_api_client_v3.models.multi_search_results import MultiSearchResult
from ffbb_api_client_v3.models.multi_search_results_class import MultiSearchResults
from mcp.shared.exceptions import McpError

from ffbb_mcp.services import (
    _cache_calendrier,
    _cache_detail,
    _cache_lives,
    _cache_search,
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    get_calendrier_club_service,
    get_competition_service,
    get_organisme_service,
    get_saisons_service,
    multi_search_service,
)


@pytest.fixture(autouse=True)
def clear_caches():
    _cache_lives.clear()
    _cache_search.clear()
    _cache_detail.clear()
    _cache_calendrier.clear()
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

    @pytest.mark.asyncio
    async def test_raises_mcp_error_when_competition_id_not_numeric(
        self, patch_get_client, mock_client
    ):
        with pytest.raises(McpError):
            await get_competition_service(competition_id="abc")

    @pytest.mark.asyncio
    async def test_cache_key_is_canonical_for_numeric_ids(
        self, patch_get_client, mock_client
    ):
        comp_mock = MagicMock()
        comp_mock.model_dump = MagicMock(return_value={"id": "123", "nom": "Comp"})
        mock_client.get_competition_async = AsyncMock(return_value=comp_mock)

        result1 = await get_competition_service(competition_id="123")
        result2 = await get_competition_service(competition_id=123)

        assert result1["id"] == "123"
        assert result2["id"] == "123"
        mock_client.get_competition_async.assert_awaited_once()


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
        mock_data = {
            "nom": "Club",
            "engagements": [
                {
                    "idCompetition": {"nom": "U11M", "categorie": {"code": "U11"}},
                    "idPoule": {"id": "p1"},
                },
                {
                    "idCompetition": {"nom": "U13F", "categorie": {"code": "U13"}},
                    "idPoule": {"id": "p2"},
                },
            ],
        }
        org_mock.model_dump = MagicMock(return_value=mock_data)
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
    async def test_returns_empty_when_no_teams(self, patch_get_client, mock_client):
        # Mock empty engagements
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(return_value={"nom": "Club", "engagements": []})
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        result = await get_calendrier_club_service(organisme_id=123)
        assert result == []

    @pytest.mark.asyncio
    async def test_full_workflow(self, patch_get_client, mock_client):
        # 1. Mock get_organisme (for teams)
        org_mock = MagicMock()
        mock_org_data = {
            "nom": "CLERMONT",
            "engagements": [
                {
                    "id": 1001,
                    "idCompetition": {
                        "id": 101,
                        "nom": "U13F",
                        "categorie": {"code": "U13"},
                    },
                    "idPoule": {"id": 201},
                    "numeroEquipe": 1,
                }
            ],
        }
        org_mock.model_dump = MagicMock(return_value=mock_org_data)
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        # 2. Mock get_poule (for matches)
        poule_mock = MagicMock()
        poule_mock.model_dump = MagicMock(
            return_value={
                "rencontres": [
                    {
                        "id": "m1",
                        "date_rencontre": "2024-03-08",
                        "nomEquipe1": "CLERMONT",
                        "nomEquipe2": "AUTRE",
                        "resultatEquipe1": 50,
                        "resultatEquipe2": 40,
                        "idEngagementEquipe1": {"id": 1001},
                        "idEngagementEquipe2": {"id": 1002},
                    }
                ]
            }
        )
        mock_client.get_poule_async = AsyncMock(return_value=poule_mock)

        result = await get_calendrier_club_service(organisme_id=123)
        assert len(result) == 1
        assert result[0]["equipe1"] == "CLERMONT"
        assert result[0]["score_equipe1"] == 50

    @pytest.mark.asyncio
    async def test_ignores_team_without_poule_and_keeps_alignment(
        self, patch_get_client, mock_client
    ):
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "nom": "CLERMONT",
                "engagements": [
                    {
                        "id": 1001,
                        "idCompetition": {
                            "id": 101,
                            "nom": "U13F",
                            "categorie": {"code": "U13"},
                        },
                        "idPoule": {},
                        "numeroEquipe": 1,
                    },
                    {
                        "id": 1002,
                        "idCompetition": {
                            "id": 102,
                            "nom": "U13F",
                            "categorie": {"code": "U13"},
                        },
                        "idPoule": {"id": 201},
                        "numeroEquipe": 2,
                    },
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        poule_mock = MagicMock()
        poule_mock.model_dump = MagicMock(
            return_value={
                "rencontres": [
                    {
                        "id": "m2",
                        "date_rencontre": "2024-03-09",
                        "nomEquipe1": "CLERMONT",
                        "nomEquipe2": "AUTRE",
                        "resultatEquipe1": 60,
                        "resultatEquipe2": 55,
                        "idEngagementEquipe1": {"id": 1002},
                        "idEngagementEquipe2": {"id": 2002},
                    }
                ]
            }
        )
        mock_client.get_poule_async = AsyncMock(return_value=poule_mock)

        result = await get_calendrier_club_service(organisme_id=123)
        assert len(result) == 1
        assert result[0]["id"] == "m2"


# ---------------------------------------------------------------------------
# Tests — multi_search_service
# ---------------------------------------------------------------------------


class TestMultiSearchService:
    @pytest.mark.asyncio
    async def test_multi_search_success(self, patch_get_client, mock_client):
        mock_res = MagicMock(spec=MultiSearchResults)
        res1 = MagicMock(spec=MultiSearchResult)
        res1.index_uid = "organismes"
        res1.hits = [{"id": 1, "nom": "Club Test"}]
        mock_res.results = [res1]

        mock_client.multi_search_async = AsyncMock(return_value=mock_res)

        result = await multi_search_service("test")
        assert len(result) == 1
        assert result[0]["_type"] == "organismes"
        assert result[0]["nom"] == "Club Test"
