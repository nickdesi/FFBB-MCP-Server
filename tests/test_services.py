"""Tests unitaires des services FFBB (avec mocks, sans appel réseau)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from ffbb_api_client_v3.models.multi_search_results import MultiSearchResult
from ffbb_api_client_v3.models.multi_search_results_class import MultiSearchResults
from mcp.shared.exceptions import McpError

from ffbb_mcp.services import (
    _cache_bilan,
    _cache_calendrier,
    _cache_detail,
    _cache_lives,
    _cache_search,
    _inflight_bilan,
    _inflight_calendrier,
    _inflight_detail,
    _inflight_search,
    ffbb_bilan_service,
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    ffbb_resolve_team_service,
    get_calendrier_club_service,
    get_competition_service,
    get_organisme_service,
    get_poule_service,
    get_saisons_service,
    multi_search_service,
    search_organismes_service,
)


@pytest.fixture(autouse=True)
def clear_caches():
    _cache_lives.clear()
    _cache_search.clear()
    _cache_detail.clear()
    _cache_calendrier.clear()
    _cache_bilan.clear()
    _inflight_detail.clear()
    _inflight_search.clear()
    _inflight_calendrier.clear()
    _inflight_bilan.clear()
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
                "id": 123,
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
# Tests — ffbb_bilan_service
# ---------------------------------------------------------------------------


class TestBilanService:
    def _make_org_mock(self, org_id="9326", nom="SCBA", engagements=None):
        m = MagicMock()
        m.model_dump = MagicMock(
            return_value={"id": org_id, "nom": nom, "engagements": engagements or []}
        )
        return m

    def _make_poule_mock(self, poule_id, engagement_id, org_id, gagnes, perdus, pm, pe):
        m = MagicMock()
        m.model_dump = MagicMock(
            return_value={
                "id": poule_id,
                "rencontres": [],
                "classements": [
                    {
                        "id_engagement": {"id": engagement_id, "numero_equipe": "1"},
                        "organisme_id": org_id,
                        "position": 1,
                        "match_joues": gagnes + perdus,
                        "gagnes": gagnes,
                        "perdus": perdus,
                        "nuls": 0,
                        "paniers_marques": pm,
                        "paniers_encaisses": pe,
                        "difference": pm - pe,
                    }
                ],
            }
        )
        return m

    @pytest.mark.asyncio
    async def test_error_when_club_not_found(self, patch_get_client, mock_client):
        mock_client.search_organismes_async = AsyncMock(return_value=MagicMock(hits=[]))
        result = await ffbb_bilan_service(club_name="Inconnu", categorie="U11M1")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_error_when_no_equipes(self, patch_get_client, mock_client):
        org_mock = self._make_org_mock(engagements=[])
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)
        result = await ffbb_bilan_service(organisme_id=9326, categorie="U17F1")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_aggregates_two_phases(self, patch_get_client, mock_client):
        """Bilan sur 2 poules : 3V+6V = 9V, paniers agrégés."""
        org_mock = self._make_org_mock(
            org_id="9326",
            nom="SCBA",
            engagements=[
                {
                    "id": "eng1",
                    "numeroEquipe": "1",
                    "idCompetition": {
                        "nom": "Dépt U11M Phase 1",
                        "id": "c1",
                        "sexe": "M",
                        "categorie": {"code": "u11"},
                        "competition_origine_niveau": 1,
                    },
                    "idPoule": {"id": "1001"},
                },
                {
                    "id": "eng2",
                    "numeroEquipe": "1",
                    "idCompetition": {
                        "nom": "Dépt U11M Phase 2",
                        "id": "c2",
                        "sexe": "M",
                        "categorie": {"code": "u11"},
                        "competition_origine_niveau": 2,
                    },
                    "idPoule": {"id": "1002"},
                },
            ],
        )
        poule1 = self._make_poule_mock(
            "1001", "eng1", "9326", gagnes=3, perdus=0, pm=150, pe=40
        )
        poule2 = self._make_poule_mock(
            "1002", "eng2", "9326", gagnes=6, perdus=0, pm=300, pe=100
        )

        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)
        mock_client.get_poule_async = AsyncMock(side_effect=[poule1, poule2])

        result = await ffbb_bilan_service(organisme_id=9326, categorie="U11M1")

        assert result["club"] == "SCBA"
        assert result["bilan_total"]["gagnes"] == 9
        assert result["bilan_total"]["perdus"] == 0
        assert result["bilan_total"]["match_joues"] == 9
        assert result["bilan_total"]["paniers_marques"] == 450
        assert result["bilan_total"]["paniers_encaisses"] == 140
        assert result["bilan_total"]["difference"] == 310
        assert len(result["phases"]) == 2

    @pytest.mark.asyncio
    async def test_uses_cache_on_second_call(self, patch_get_client, mock_client):
        """Le deuxième appel identique ne doit pas rappeler l'API."""
        org_mock = self._make_org_mock(
            org_id="9326",
            engagements=[
                {
                    "id": "eng1",
                    "numeroEquipe": "1",
                    "idCompetition": {
                        "nom": "Dépt U11M",
                        "id": "c1",
                        "sexe": "M",
                        "categorie": {"code": "u11"},
                        "competition_origine_niveau": 1,
                    },
                    "idPoule": {"id": "p1"},
                }
            ],
        )
        poule1 = self._make_poule_mock(
            "1001", "eng1", "9326", gagnes=3, perdus=0, pm=100, pe=30
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)
        mock_client.get_poule_async = AsyncMock(return_value=poule1)

        await ffbb_bilan_service(organisme_id=9326, categorie="U11M1")
        await ffbb_bilan_service(organisme_id=9326, categorie="U11M1")

        # L'organisme n'est appelé qu'une fois grâce au cache bilan
        mock_client.get_organisme_async.assert_awaited_once()




# ---------------------------------------------------------------------------
# Tests — get_calendrier_club_service
# ---------------------------------------------------------------------------


class TestCalendrierClubService:
    @pytest.mark.asyncio
    async def test_caches_empty_when_club_not_found(
        self, patch_get_client, mock_client
    ):
        mock_client.search_organismes_async = AsyncMock(return_value=None)

        result_1 = await get_calendrier_club_service(club_name="club fantome")
        result_2 = await get_calendrier_club_service(club_name="club fantome")

        assert result_1 == []
        assert result_2 == []
        mock_client.search_organismes_async.assert_awaited_once()

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
    async def test_deduplicates_poule_fetches(self, patch_get_client, mock_client):
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "nom": "CLERMONT",
                "engagements": [
                    {
                        "id": 1001,
                        "idCompetition": {
                            "id": 101,
                            "nom": "U11M-1",
                            "categorie": {"code": "U11"},
                        },
                        "idPoule": {"id": 201},
                        "numeroEquipe": 1,
                    },
                    {
                        "id": 1002,
                        "idCompetition": {
                            "id": 102,
                            "nom": "U11M-2",
                            "categorie": {"code": "U11"},
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
                        "id": "m1",
                        "date_rencontre": "2024-03-08",
                        "nomEquipe1": "CLERMONT - 1",
                        "nomEquipe2": "AUTRE",
                        "resultatEquipe1": 50,
                        "resultatEquipe2": 40,
                        "idEngagementEquipe1": {"id": 1001},
                        "idEngagementEquipe2": {"id": 9991},
                    },
                    {
                        "id": "m2",
                        "date_rencontre": "2024-03-09",
                        "nomEquipe1": "AUTRE",
                        "nomEquipe2": "CLERMONT - 2",
                        "resultatEquipe1": 35,
                        "resultatEquipe2": 45,
                        "idEngagementEquipe1": {"id": 9992},
                        "idEngagementEquipe2": {"id": 1002},
                    },
                ]
            }
        )
        mock_client.get_poule_async = AsyncMock(return_value=poule_mock)

        result = await get_calendrier_club_service(organisme_id=123)

        assert len(result) == 2
        assert mock_client.get_poule_async.await_count == 1

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

    @pytest.mark.asyncio
    async def test_truncates_when_too_many_matches(
        self, patch_get_client, mock_client, monkeypatch
    ):
        # Force une petite limite pour le test
        monkeypatch.setenv("FFBB_MAX_CALENDAR_MATCHES", "3")

        # 0. Mock get_organisme (requis par _resolve_club_and_org)
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(return_value={"id": 123, "nom": "Club", "engagements": []})
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        # 1. Mock ffbb_equipes_club_service pour renvoyer une equipe valable
        async def _fake_equipes_club_service(organisme_id: int | str, filtre: str | None = None):
            return [
                {
                    "engagement_id": 1001,
                    "poule_id": 2001,
                    "nom_equipe": "CLERMONT",
                    "competition": "U13F",
                }
            ]

        monkeypatch.setattr(
            "ffbb_mcp.services.ffbb_equipes_club_service",
            _fake_equipes_club_service,
        )

        # 2. Mock get_poule avec beaucoup de rencontres
        poule_mock = MagicMock()
        rencontres = []
        for i in range(10):
            rencontres.append(
                {
                    "id": i,
                    "date_rencontre": f"2024-01-{i+1:02d}",
                    "nomEquipe1": "CLERMONT",
                    "nomEquipe2": "AUTRE",
                    "resultatEquipe1": 50 + i,
                    "resultatEquipe2": 40 + i,
                }
            )
        poule_mock.model_dump = MagicMock(
            return_value={
                "id": 2001,
                "rencontres": rencontres,
                "classements": [],
            }
        )
        mock_client.get_poule_async = AsyncMock(return_value=poule_mock)

        result = await get_calendrier_club_service(organisme_id=123, categorie="U13F")

        # On doit avoir 3 matchs + 1 warning
        assert len(result) == 4
        matches = result[:-1]
        warning = result[-1]

        # Vérifie que seuls les 3 plus récents (dates les plus grandes) sont présents
        dates = [m["date"] for m in matches]
        assert dates == sorted(dates, reverse=True)
        assert len(matches) == 3

        assert "warning" in warning
        assert "Résultat tronqué" in warning["warning"]


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

    @pytest.mark.asyncio
    async def test_uses_weighted_index_limits(self, patch_get_client, mock_client):
        mock_res = MagicMock(spec=MultiSearchResults)
        mock_res.results = []
        mock_client.multi_search_async = AsyncMock(return_value=mock_res)

        await multi_search_service("test", limit=20)

        queries = mock_client.multi_search_async.await_args.args[0]
        assert queries[0].limit == 7
        assert queries[1].limit == 7
        assert queries[2].limit == 7
        assert queries[3].limit == 2
        assert queries[4].limit == 2
        assert queries[5].limit == 2
        assert queries[6].limit == 2

    @pytest.mark.asyncio
    async def test_caches_empty_multi_search_results(
        self, patch_get_client, mock_client
    ):
        mock_res = MagicMock(spec=MultiSearchResults)
        mock_res.results = []
        mock_client.multi_search_async = AsyncMock(return_value=mock_res)

        result_1 = await multi_search_service("club inconnu", limit=10)
        result_2 = await multi_search_service("club inconnu", limit=10)

        assert result_1 == []
        assert result_2 == []
        mock_client.multi_search_async.assert_awaited_once()


class TestSearchCaching:
    @pytest.mark.asyncio
    async def test_caches_empty_search_results(self, patch_get_client, mock_client):
        mock_client.search_organismes_async = AsyncMock(return_value=None)

        result_1 = await search_organismes_service("club inexistant", limit=5)
        result_2 = await search_organismes_service("club inexistant", limit=5)

        assert result_1 == []
        assert result_2 == []
        mock_client.search_organismes_async.assert_awaited_once()


class TestGetPouleService:
    @pytest.mark.asyncio
    async def test_coalesces_concurrent_requests(self, patch_get_client, mock_client):
        poule_mock = MagicMock()
        poule_mock.model_dump = MagicMock(return_value={"id": 123, "rencontres": []})

        async def delayed_poule(*, poule_id):
            await asyncio.sleep(0)
            return poule_mock

        mock_client.get_poule_async = AsyncMock(side_effect=delayed_poule)

        result1, result2 = await asyncio.gather(
            get_poule_service(123),
            get_poule_service(123),
        )

        assert result1 == {"id": 123, "rencontres": []}
        assert result2 == {"id": 123, "rencontres": []}
        assert mock_client.get_poule_async.await_count == 1


# ---------------------------------------------------------------------------
# Tests — ffbb_resolve_team_service
# ---------------------------------------------------------------------------


class TestResolveTeamService:
    @pytest.mark.asyncio
    async def test_resolved_single_team(self, patch_get_client, mock_client):
        """Une seule équipe correspondante -> status resolved et team non nul."""

        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 123,
                "nom": "Club Test",
                "engagements": [
                    {
                        "id": "eng1",
                        "idCompetition": {
                            "nom": "U11M",
                            "categorie": {"code": "U11"},
                        },
                        "idPoule": {"id": "p1"},
                    }
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        result = await ffbb_resolve_team_service(
            organisme_id=123,
            club_name=None,
            categorie="U11M1",
        )

        assert result.get("status") == "resolved"
        assert result.get("team") is not None
        assert result.get("candidates")

    @pytest.mark.asyncio
    async def test_ambiguous_multiple_teams(self, patch_get_client, mock_client):
        """Plusieurs équipes candidates -> status ambiguous et candidates non vides."""

        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "nom": "Club Test",
                "engagements": [
                    {
                        "id": "eng1",
                        "idCompetition": {
                            "nom": "U11M1",
                            "categorie": {"code": "U11"},
                        },
                        "idPoule": {"id": "p1"},
                    },
                    {
                        "id": "eng2",
                        "idCompetition": {
                            "nom": "U11M2",
                            "categorie": {"code": "U11"},
                        },
                        "idPoule": {"id": "p2"},
                    },
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        result = await ffbb_resolve_team_service(
            organisme_id=123,
            club_name=None,
            categorie="U11M",
        )

        assert result.get("status") == "ambiguous"
        assert result.get("team") is None or result.get("team") == {}
        assert result.get("candidates")
        assert isinstance(result.get("candidates"), list)

    @pytest.mark.asyncio
    async def test_not_found_when_no_matching_team(
        self, patch_get_client, mock_client
    ):
        """Aucune équipe ne matche -> status not_found et message explicite."""

        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 123,
                "nom": "Club Test",
                "engagements": [],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        result = await ffbb_resolve_team_service(
            organisme_id=123,
            club_name=None,
            categorie="U11M1",
        )

        assert result.get("status") == "not_found"
        assert result.get("team") is None or result.get("team") == {}
        assert not result.get("candidates")
        assert "message" in result or "ambiguity" in result
