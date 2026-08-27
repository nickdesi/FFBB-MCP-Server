"""Tests unitaires des services FFBB (avec mocks, sans appel réseau)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cachetools import TTLCache
from ffbb_data_client.models.multi_search_results import MultiSearchResult
from ffbb_data_client.models.multi_search_results_class import MultiSearchResults
from mcp.shared.exceptions import McpError

from ffbb_mcp import services
from ffbb_mcp._state import reset_service_state
from ffbb_mcp.services import (
    _extract_club_key_word,
    ffbb_bilan_service,
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    ffbb_resolve_team_service,
    get_calendrier_club_service,
    get_competition_service,
    get_organisme_service,
    get_poule_service,
    get_rencontre_service,
    get_saisons_service,
    multi_search_service,
    search_organismes_service,
)
from ffbb_mcp.services.search import (
    _add_truncation_meta,
    _deduplicate_same_team_phases,
    _phase_sort_key,
)


@pytest.fixture(autouse=True)
def clear_caches():
    reset_service_state()

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
        from ffbb_mcp.services.poule import _SAISONS_FIELDS

        def mock_get_saisons(fields=None, filter_criteria=None):
            data = [
                {"id": 1, "nom": "2023-2024", "actif": False},
                {"id": 2, "nom": "2024-2025", "actif": True},
            ]
            if filter_criteria:
                return [d for d in data if d.get("actif")]
            return data

        mock_client.get_saisons_async = AsyncMock(side_effect=mock_get_saisons)

        result_active = await get_saisons_service(active_only=True)
        assert len(result_active) == 1
        assert result_active[0]["nom"] == "2024-2025"
        mock_client.get_saisons_async.assert_awaited_once_with(
            fields=_SAISONS_FIELDS,
            filter_criteria='{"actif": {"_eq": true}}',
        )


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
        with pytest.raises(McpError):
            await get_organisme_service(organisme_id=99999)


class TestGetRencontreService:
    @pytest.mark.asyncio
    async def test_enriches_salle_details(self, patch_get_client, mock_client):
        rencontre_mock = MagicMock()
        rencontre_mock.model_dump = MagicMock(
            return_value={"id": "m1", "salle": {"id": "s1"}}
        )
        salle_mock = MagicMock()
        salle_mock.model_dump = MagicMock(
            return_value={
                "id": "s1",
                "nom": "Gymnase Test",
                "adresse": "1 rue du Basket",
                "codePostal": "63000",
                "ville": "Clermont-Ferrand",
            }
        )
        mock_client.get_rencontre_async = AsyncMock(return_value=rencontre_mock)
        mock_client.get_salle_async = AsyncMock(return_value=salle_mock)

        result = await get_rencontre_service("m1")

        mock_client.get_rencontre_async.assert_awaited_once_with("m1")
        mock_client.get_salle_async.assert_awaited_once_with("s1")
        assert result["salle_details"]["nom"] == "Gymnase Test"
        assert result["adresse_salle"] == "1 rue du Basket 63000 Clermont-Ferrand"

    @pytest.mark.asyncio
    async def test_does_not_call_salle_when_missing(
        self, patch_get_client, mock_client
    ):
        rencontre_mock = MagicMock()
        rencontre_mock.model_dump = MagicMock(return_value={"id": "m1"})
        mock_client.get_rencontre_async = AsyncMock(return_value=rencontre_mock)

        result = await get_rencontre_service("m1")

        assert result == {"id": "m1"}
        mock_client.get_salle_async.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests — ffbb_equipes_club_service
# ---------------------------------------------------------------------------


class TestEquipesClubService:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_org(self, patch_get_client, mock_client):
        mock_client.get_organisme_async = AsyncMock(return_value=None)
        with pytest.raises(McpError):
            await ffbb_equipes_club_service(organisme_id=123)

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

    def _make_poule_mock(
        self,
        poule_id,
        engagement_id,
        org_id,
        gagnes,
        perdus,
        pm,
        pe,
        numero_equipe="1",
        nombre_forfaits=0,
        nombre_defauts=0,
    ):
        m = MagicMock()
        m.model_dump = MagicMock(
            return_value={
                "id": poule_id,
                "rencontres": [],
                "classements": [
                    {
                        "id_engagement": {
                            "id": engagement_id,
                            "numero_equipe": numero_equipe,
                        },
                        "organisme_id": org_id,
                        "position": 1,
                        "match_joues": gagnes
                        + perdus
                        + nombre_forfaits
                        + nombre_defauts,
                        "gagnes": gagnes,
                        "perdus": perdus,
                        "nuls": 0,
                        "paniers_marques": pm,
                        "paniers_encaisses": pe,
                        "difference": pm - pe,
                        "nombre_forfaits": nombre_forfaits,
                        "nombre_defauts": nombre_defauts,
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
        assert "suggestion" in result
        assert result["next_call"] == "ffbb_search(type='organismes', query='Inconnu')"
        assert result["_meta"]["cache"] == "bilan"

    @pytest.mark.asyncio
    async def test_error_when_no_equipes(self, patch_get_client, mock_client):
        org_mock = self._make_org_mock(engagements=[])
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)
        result = await ffbb_bilan_service(organisme_id=9326, categorie="U17F1")
        assert "error" in result
        assert "suggestion" in result
        assert result["next_call"] == "ffbb_club(action='equipes', organisme_id=9326)"
        assert result["_meta"]["cache"] == "bilan"

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
    async def test_numero_equipe_present_in_phases(self, patch_get_client, mock_client):
        """Lors de 2 équipes dans la même catégorie, chaque phase contient
        le bon numero_equipe (1 ou 2) pour permettre l'attribution sans ambiguïté."""
        org_mock = self._make_org_mock(
            org_id="9326",
            nom="GERZAT BASKET",
            engagements=[
                {
                    "id": "engA",
                    "numeroEquipe": "1",
                    "idCompetition": {
                        "nom": "DF2 Phase 1",
                        "id": "c1",
                        "sexe": "F",
                        "categorie": {"code": "senior"},
                        "competition_origine_niveau": 1,
                    },
                    "idPoule": {"id": "2001"},
                },
                {
                    "id": "engB",
                    "numeroEquipe": "2",
                    "idCompetition": {
                        "nom": "DF2 Phase 1",
                        "id": "c1",
                        "sexe": "F",
                        "categorie": {"code": "senior"},
                        "competition_origine_niveau": 1,
                    },
                    "idPoule": {"id": "2002"},
                },
            ],
        )
        poule1 = self._make_poule_mock(
            "2001",
            "engA",
            "9326",
            gagnes=1,
            perdus=7,
            pm=283,
            pe=419,
            numero_equipe="1",
        )
        poule2 = self._make_poule_mock(
            "2002",
            "engB",
            "9326",
            gagnes=0,
            perdus=8,
            pm=223,
            pe=633,
            numero_equipe="2",
        )

        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)
        mock_client.get_poule_async = AsyncMock(side_effect=[poule1, poule2])

        result = await ffbb_bilan_service(organisme_id=9326, categorie="SeniorF")

        phases = result["phases"]
        assert len(phases) == 2

        phase_by_poule = {p["poule_id"]: p for p in phases}
        assert phase_by_poule["2001"]["numero_equipe"] == "1"
        assert phase_by_poule["2002"]["numero_equipe"] == "2"

        # La structure groupée doit isoler les deux équipes sans ambiguïté
        equipes_bilan = result["equipes_bilan"]
        assert set(equipes_bilan.keys()) == {"1", "2"}
        assert equipes_bilan["1"]["bilan"]["gagnes"] == 1
        assert equipes_bilan["2"]["bilan"]["gagnes"] == 0
        assert equipes_bilan["1"]["bilan"]["perdus"] == 7
        assert equipes_bilan["2"]["bilan"]["perdus"] == 8

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

    @pytest.mark.asyncio
    async def test_aggregates_with_forfaits_and_defauts(
        self, patch_get_client, mock_client
    ):
        """Bilan avec forfait et défaut : J = V + D bruts + forfaits + defauts."""
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
                    "idPoule": {"id": "1001"},
                }
            ],
        )
        poule1 = self._make_poule_mock(
            "1001",
            "eng1",
            "9326",
            gagnes=4,
            perdus=1,
            pm=226,
            pe=201,
            nombre_forfaits=1,
            nombre_defauts=1,
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)
        mock_client.get_poule_async = AsyncMock(return_value=poule1)

        result = await ffbb_bilan_service(organisme_id=9326, categorie="U11M1")

        assert result["bilan_total"]["match_joues"] == 7
        assert result["bilan_total"]["gagnes"] == 4
        assert result["bilan_total"]["perdus"] == 3  # 1 perdus + 1 forfait + 1 défaut
        assert result["bilan_total"]["difference"] == 25
        assert result["phases"][0]["total_equipes"] == 1


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
        call_count_after_first = mock_client.search_organismes_async.await_count

        result_2 = await get_calendrier_club_service(club_name="club fantome")

        # _build_calendar_matches now returns an error dict instead of []
        assert isinstance(result_1, list) and len(result_1) == 1
        assert "error" in result_1[0]
        assert result_1 == result_2
        # The second call should be served from cache — no additional API calls.
        assert mock_client.search_organismes_async.await_count == call_count_after_first

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_teams(self, patch_get_client, mock_client):
        # Mock empty engagements
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(return_value={"nom": "Club", "engagements": []})
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        result = await get_calendrier_club_service(organisme_id=123)
        assert len(result) == 1
        assert "warning" in result[0]
        assert "équipes engagées" in result[0]["warning"]
        assert result[0]["equipes"] == []

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
                        "salle": {"id": "s1"},
                    }
                ]
            }
        )
        mock_client.get_poule_async = AsyncMock(return_value=poule_mock)
        salle_mock = MagicMock()
        salle_mock.model_dump = MagicMock(
            return_value={"id": "s1", "adresse1": "2 avenue du Sport", "ville": "Riom"}
        )
        mock_client.get_salle_async = AsyncMock(return_value=salle_mock)

        result = await get_calendrier_club_service(organisme_id=123)
        assert len(result) == 1
        assert result[0]["equipe1"] == "CLERMONT"
        assert result[0]["score_equipe1"] == 50
        assert result[0]["salle_details"]["id"] == "s1"
        assert result[0]["adresse_salle"] == "2 avenue du Sport Riom"

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
        monkeypatch.setattr("ffbb_mcp.services._MAX_CALENDAR_MATCHES", 3)

        # 0. Mock get_organisme (requis par resolve_club_and_org)
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={"id": 123, "nom": "Club", "engagements": []}
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        # 1. Mock ffbb_equipes_club_service pour renvoyer une equipe valable
        async def _fake_equipes_club_service(
            organisme_id: int | str, filtre: str | None = None
        ):
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
                    "date_rencontre": f"2024-01-{i + 1:02d}",
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

    @pytest.mark.asyncio
    async def test_calendrier_filters_matches_to_club_team_only(
        self, patch_get_client, mock_client
    ):
        """Vérifie que les matchs entre équipes tierces dans la même poule sont exclus du calendrier club."""
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 9326,
                "nom": "STADE CLERMONTOIS",
                "engagements": [
                    {
                        "id": 5001,
                        "idCompetition": {
                            "id": 101,
                            "nom": "Pré nationale masculine",
                            "categorie": {"code": "SE"},
                            "sexe": "M",
                        },
                        "idPoule": {"id": 2001},
                        "numeroEquipe": 1,
                    }
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        # Poule contenant 1 match du Stade Clermontois et 1 match entre deux adversaires
        poule_mock = MagicMock()
        poule_mock.model_dump = MagicMock(
            return_value={
                "id": 2001,
                "rencontres": [
                    {
                        "id": "match_our_team",
                        "date_rencontre": "2026-09-19",
                        "nomEquipe1": "OUEST LYONNAIS BASKET - 2",
                        "nomEquipe2": "STADE CLERMONTOIS - 1",
                        "idEngagementEquipe1": {"id": 9991},
                        "idEngagementEquipe2": {"id": 5001},
                    },
                    {
                        "id": "match_third_party",
                        "date_rencontre": "2026-09-19",
                        "nomEquipe1": "BEAUJOLAIS BASKET - 2",
                        "nomEquipe2": "CS PONT DU CHATEAU - 1",
                        "idEngagementEquipe1": {"id": 9992},
                        "idEngagementEquipe2": {"id": 9993},
                    },
                ],
                "classements": [],
            }
        )
        mock_client.get_poule_async = AsyncMock(return_value=poule_mock)

        result = await get_calendrier_club_service(
            organisme_id=9326, categorie="SEM", numero_equipe=1
        )

        assert len(result) == 1
        assert result[0]["id"] == "match_our_team"
        assert result[0]["equipe2"] == "STADE CLERMONTOIS - 1"


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
        assert len(queries) == 6
        assert queries[0].limit == 7
        assert queries[1].limit == 7
        assert queries[2].limit == 7
        assert queries[3].limit == 2
        assert queries[4].limit == 2
        assert queries[5].limit == 2

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

    @pytest.mark.asyncio
    async def test_multi_search_self_healing_on_failure(
        self, patch_get_client, mock_client
    ):
        from ffbb_mcp._state import state

        state.active_search_indexes = ["index_corrompu", "ffbbserver_organismes"]
        mock_res = MagicMock(spec=MultiSearchResults)
        mock_res.results = [
            MagicMock(
                index_uid="ffbbserver_organismes", hits=[], estimated_total_hits=0
            )
        ]

        # Premier appel échoue (ValueError zip), le second (healed) réussit
        mock_client.multi_search_async = AsyncMock(
            side_effect=[ValueError("zip() mismatch"), mock_res]
        )

        # Mock pour le diagnostic probe
        probe_res_ok = MagicMock(results=[MagicMock()])
        mock_client._meilisearch.multi_search_async = AsyncMock(
            side_effect=[Exception("failed"), probe_res_ok]
        )

        result = await multi_search_service("test self healing", limit=10)
        assert isinstance(result, list)
        assert state.active_search_indexes == ["ffbbserver_organismes"]
        assert mock_client.multi_search_async.await_count == 2


class TestSearchCaching:
    @pytest.mark.asyncio
    async def test_caches_empty_search_results(self, patch_get_client, mock_client):
        mock_client.search_organismes_async = AsyncMock(return_value=None)

        result_1 = await search_organismes_service("club inexistant", limit=5)
        result_2 = await search_organismes_service("club inexistant", limit=5)

        assert result_1 == []
        assert result_2 == []
        mock_client.search_organismes_async.assert_awaited_once()


class TestTruncationMeta:
    """Tests pour la méta-donnée de troncature _meta dans ffbb_search."""

    def test_add_truncation_meta_with_total(self):
        result = [{"nom": "A", "_total_hits": 50}, {"nom": "B"}]
        out = _add_truncation_meta(result)
        assert out[0]["_meta"] is True
        assert out[0]["total"] == 50
        assert out[0]["returned"] == 2
        assert out[0]["truncated"] is True
        assert "_total_hits" not in out[0]
        assert "_total_hits" not in out[1]

    def test_add_truncation_meta_no_truncation(self):
        result = [{"nom": "A"}, {"nom": "B"}]
        out = _add_truncation_meta(result)
        assert len(out) == 2
        assert "_meta" not in out[0]

    def test_add_truncation_meta_empty(self):
        assert _add_truncation_meta([]) == []

    def test_add_truncation_meta_strips_total_hits(self):
        result = [{"nom": "A", "_total_hits": 10}, {"nom": "B", "_total_hits": 10}]
        out = _add_truncation_meta(result)
        for item in out:
            assert "_total_hits" not in item

    @pytest.mark.asyncio
    async def test_multi_search_truncated(self, patch_get_client, mock_client):
        from ffbb_mcp.services import multi_search_service

        mock_res = MagicMock(spec=MultiSearchResults)
        res1 = MagicMock(spec=MultiSearchResult)
        res1.index_uid = "organismes"
        res1.estimated_total_hits = 50
        res1.hits = [{"id": i, "nom": f"Club {i}"} for i in range(20)]
        mock_res.results = [res1]
        mock_client.multi_search_async = AsyncMock(return_value=mock_res)

        result = await multi_search_service("test", limit=10)
        assert len(result) == 10
        assert result[0]["_total_hits"] == 50

    @pytest.mark.asyncio
    async def test_multi_search_not_truncated(self, patch_get_client, mock_client):
        from ffbb_mcp.services import multi_search_service

        mock_res = MagicMock(spec=MultiSearchResults)
        res1 = MagicMock(spec=MultiSearchResult)
        res1.index_uid = "organismes"
        res1.estimated_total_hits = 5
        res1.hits = [{"id": i, "nom": f"Club {i}"} for i in range(5)]
        mock_res.results = [res1]
        mock_client.multi_search_async = AsyncMock(return_value=mock_res)

        result = await multi_search_service("test", limit=20)
        assert len(result) == 5
        assert "_total_hits" not in result[0]

    @pytest.mark.asyncio
    async def test_ffbb_search_adds_meta_when_truncated(
        self, patch_get_client, mock_client
    ):
        from ffbb_mcp.services import ffbb_search_service

        mock_res = MagicMock(spec=MultiSearchResults)
        res1 = MagicMock(spec=MultiSearchResult)
        res1.index_uid = "organismes"
        res1.estimated_total_hits = 50
        res1.hits = [{"id": i, "nom": f"Club {i}"} for i in range(20)]
        mock_res.results = [res1]
        mock_client.multi_search_async = AsyncMock(return_value=mock_res)

        result = await ffbb_search_service(query="test", type="all", limit=10)
        assert result[0]["_meta"] is True
        assert result[0]["total"] == 50
        assert result[0]["truncated"] is True
        assert len(result) == 11  # _meta + 10 results


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

        expected = {
            "id": 123,
            "rencontres": [],
            "phase_terminee": True,
            "phase_type": "poule",
            "rencontres_restantes_par_equipe": {},
        }
        assert result1.get("data", result1) == expected
        assert result2.get("data", result2) == expected
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
    async def test_not_found_when_no_matching_team(self, patch_get_client, mock_client):
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

    @pytest.mark.asyncio
    async def test_resolve_team_without_categorie_returns_club_teams_ambiguous(
        self, patch_get_client, mock_client
    ):
        """Sans catégorie, ffbb_resolve_team retourne toutes les équipes du club comme candidats."""
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 123,
                "nom": "Club Multi Equipes",
                "engagements": [
                    {
                        "id": "eng1",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "U11M1",
                            "sexe": "M",
                            "categorie": {"code": "U11"},
                        },
                        "idPoule": {"id": "p1"},
                    },
                    {
                        "id": "eng2",
                        "numeroEquipe": "2",
                        "idCompetition": {
                            "nom": "SEM2",
                            "sexe": "M",
                            "categorie": {"code": "SE"},
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
            categorie=None,
        )

        assert result.get("status") == "ambiguous"
        assert result.get("team") is None
        assert len(result.get("candidates", [])) == 2
        assert "préciser la catégorie" in (result.get("ambiguity") or "")

    @pytest.mark.asyncio
    async def test_resolve_team_without_categorie_single_team_resolved(
        self, patch_get_client, mock_client
    ):
        """Sans catégorie, si le club n'a qu'une seule équipe, elle est résolue directement."""
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 123,
                "nom": "Club Mono Equipe",
                "engagements": [
                    {
                        "id": "eng1",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "SEM1",
                            "sexe": "M",
                            "categorie": {"code": "SE"},
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
            categorie=None,
        )

        assert result.get("status") == "resolved"
        assert result.get("team") is not None
        assert result.get("team", {}).get("team_label") == "SEM1"

    @pytest.mark.asyncio
    async def test_resolve_team_gender_filtering_rm1_auto_resolves_club(
        self, patch_get_client, mock_client
    ):
        """Une recherche club_name avec RM1 élimine le club féminin et résout l'équipe."""
        club_fem = MagicMock()
        club_fem.model_dump = MagicMock(
            return_value={"id": 9269, "nom": "STADE CLERMONTOIS BASKET FEMININ"}
        )
        club_masc = MagicMock()
        club_masc.model_dump = MagicMock(
            return_value={"id": 9326, "nom": "STADE CLERMONTOIS BASKET AUVERGNE"}
        )
        search_res = MagicMock()
        search_res.hits = [club_fem, club_masc]
        search_res.estimated_total_hits = 2

        mock_client.search_organismes_async = AsyncMock(return_value=search_res)

        org_masc_data = {
            "id": 9326,
            "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
            "engagements": [
                {
                    "id": "eng_rm1",
                    "numeroEquipe": "1",
                    "idCompetition": {
                        "id": "comp_1",
                        "nom": "Pré nationale masculine",
                        "sexe": "M",
                        "categorie": {"code": "SE"},
                    },
                    "idPoule": {"id": "poule_1"},
                }
            ],
        }
        mock_client.get_organisme_async = AsyncMock(
            return_value=MagicMock(model_dump=MagicMock(return_value=org_masc_data))
        )

        result = await ffbb_resolve_team_service(
            club_name="Stade Clermontois",
            categorie="RM1",
        )

        assert result.get("status") == "resolved"
        assert result.get("team") is not None
        assert (
            result.get("team", {}).get("nom_equipe")
            == "STADE CLERMONTOIS BASKET AUVERGNE"
        )
        assert result.get("club_resolu", {}).get("organisme_id") == 9326

    @pytest.mark.asyncio
    async def test_resolve_team_with_explicit_numero_equipe(
        self, patch_get_client, mock_client
    ):
        """Vérifie que numero_equipe=1 désambiguïse une catégorie non numérotée (SEM)."""
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 9326,
                "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
                "engagements": [
                    {
                        "id": "eng_sem1",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "id": "comp_1",
                            "nom": "Pré nationale masculine",
                            "sexe": "M",
                            "categorie": {"code": "SE"},
                        },
                        "idPoule": {"id": "poule_1"},
                    },
                    {
                        "id": "eng_sem2",
                        "numeroEquipe": "2",
                        "idCompetition": {
                            "id": "comp_2",
                            "nom": "Régionale masculine seniors - Division 2",
                            "sexe": "M",
                            "categorie": {"code": "SE"},
                        },
                        "idPoule": {"id": "poule_2"},
                    },
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        result = await ffbb_resolve_team_service(
            organisme_id=9326,
            categorie="SEM",
            numero_equipe=1,
        )

        assert result.get("status") == "resolved"
        assert result.get("team") is not None
        assert result.get("team", {}).get("numero_equipe") == "1"
        assert result.get("team", {}).get("competition") == "Pré nationale masculine"


# ---------------------------------------------------------------------------
# Tests — Bug 2 : fallback équipe sans numéro explicite
# ---------------------------------------------------------------------------


class TestEquipesClubFallbackNoNumero:
    """Vérifie le fallback quand une équipe n'a pas de numero_equipe enregistré."""

    def _make_org_mock_no_number(self, sexe="M", categorie_code="U11"):
        """Organsime avec une seule équipe sans numero_equipe (None)."""
        m = MagicMock()
        m.model_dump = MagicMock(
            return_value={
                "id": 42,
                "nom": "Club Solo",
                "engagements": [
                    {
                        "id": "engA",
                        "numeroEquipe": None,
                        "idCompetition": {
                            "nom": f"{categorie_code}{sexe}",
                            "id": "cA",
                            "sexe": sexe,
                            "categorie": {"code": categorie_code},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "pA"},
                    }
                ],
            }
        )
        return m

    def _make_org_mock_empty_string_number(self):
        """Organsime avec une seule équipe dont numero_equipe est une chaîne vide."""
        m = MagicMock()
        m.model_dump = MagicMock(
            return_value={
                "id": 43,
                "nom": "Club Vide",
                "engagements": [
                    {
                        "id": "engB",
                        "numeroEquipe": "",
                        "idCompetition": {
                            "nom": "U13M",
                            "id": "cB",
                            "sexe": "M",
                            "categorie": {"code": "U13"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "pB"},
                    }
                ],
            }
        )
        return m

    @pytest.mark.asyncio
    async def test_fallback_numero_none_returns_team_with_note(
        self, patch_get_client, mock_client
    ):
        """Filtre 'U11M1' avec equipe sans numero → fallback + note."""
        mock_client.get_organisme_async = AsyncMock(
            return_value=self._make_org_mock_no_number()
        )
        result = await ffbb_equipes_club_service(organisme_id=42, filtre="U11M1")

        assert len(result) == 1
        assert (
            result[0].get("note")
            == "équipe sans numéro explicite, correspond potentiellement à ce numéro"
        )
        assert result[0].get("engagement_id") == "engA"

    @pytest.mark.asyncio
    async def test_fallback_empty_string_numero_returns_team_with_note(
        self, patch_get_client, mock_client
    ):
        """Filtre 'U13M1' avec equipe dont numeroEquipe='' → team retournée avec note."""
        mock_client.get_organisme_async = AsyncMock(
            return_value=self._make_org_mock_empty_string_number()
        )
        result = await ffbb_equipes_club_service(organisme_id=43, filtre="U13M1")

        # L'équipe doit être retournée (pas d'erreur) avec la note d'implicité
        assert len(result) == 1
        assert "error" not in result[0]
        assert (
            result[0].get("note")
            == "équipe sans numéro explicite, correspond potentiellement à ce numéro"
        )
        assert result[0].get("engagement_id") == "engB"

    @pytest.mark.asyncio
    async def test_no_fallback_when_explicit_number_matches(
        self, patch_get_client, mock_client
    ):
        """Quand le numéro explicite correspond, pas de fallback ni de note."""
        m = MagicMock()
        m.model_dump = MagicMock(
            return_value={
                "id": 44,
                "nom": "Club Dual",
                "engagements": [
                    {
                        "id": "eng1",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "U11M",
                            "id": "c1",
                            "sexe": "M",
                            "categorie": {"code": "U11"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "p1"},
                    },
                    {
                        "id": "eng2",
                        "numeroEquipe": "2",
                        "idCompetition": {
                            "nom": "U11M",
                            "id": "c1",
                            "sexe": "M",
                            "categorie": {"code": "U11"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "p2"},
                    },
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=m)
        result = await ffbb_equipes_club_service(organisme_id=44, filtre="U11M1")

        assert len(result) == 1
        assert result[0].get("engagement_id") == "eng1"
        assert result[0].get("note") is None

    @pytest.mark.asyncio
    async def test_fallback_propagates_through_resolve_team(
        self, patch_get_client, mock_client
    ):
        """ffbb_resolve_team_service résout une équipe sans numéro via le fallback."""
        mock_client.get_organisme_async = AsyncMock(
            return_value=self._make_org_mock_no_number()
        )
        result = await ffbb_resolve_team_service(
            organisme_id=42, club_name=None, categorie="U11M1"
        )

        assert result.get("status") == "resolved"
        assert result.get("team") is not None
        team = result["team"]
        assert (
            team.get("note")
            == "équipe sans numéro explicite, correspond potentiellement à ce numéro"
        )

    @pytest.mark.asyncio
    async def test_fallback_wrong_category_still_returns_error(
        self, patch_get_client, mock_client
    ):
        """Si la catégorie ne correspond pas, même le fallback échoue → error."""
        mock_client.get_organisme_async = AsyncMock(
            return_value=self._make_org_mock_no_number(categorie_code="U13")
        )
        result = await ffbb_equipes_club_service(organisme_id=42, filtre="U11M1")

        assert len(result) == 1
        assert "error" in result[0]


# ---------------------------------------------------------------------------
# Tests — _extract_club_key_word
# ---------------------------------------------------------------------------


class TestExtractClubKeyWord:
    """Tests unitaires pour l'extraction du mot distinctif d'un club."""

    def test_basket_suffix_removed(self):
        assert _extract_club_key_word("Gerzat Basket") == "GERZAT"

    def test_basketball_suffix_removed(self):
        assert _extract_club_key_word("Clermont Basketball") == "CLERMONT"

    def test_bc_prefix_removed(self):
        assert _extract_club_key_word("BC Aurillac") == "AURILLAC"

    def test_full_name_no_generic_word(self):
        # "Villeurbanne" alone: key word = "VILLEURBANNE" == normalized full name → None
        result = _extract_club_key_word("Villeurbanne")
        assert result is None

    def test_multiple_words_returns_first_distinctive(self):
        result = _extract_club_key_word("Gerzat Jules Verne Basket")
        assert result == "GERZAT"

    def test_only_generic_words_returns_none(self):
        assert _extract_club_key_word("Club Basket Ball") is None

    def test_short_word_ignored(self):
        # "BC AB Gerzat": "BC" and "AB" are < 4 chars or generic, key word = "GERZAT"
        assert _extract_club_key_word("BC AB Gerzat") == "GERZAT"

    def test_empty_returns_none(self):
        assert _extract_club_key_word("") is None


# ---------------------------------------------------------------------------
# Tests — resolve_club_and_org entente detection
# ---------------------------------------------------------------------------


class TestResolveClubAndOrgEntente:
    """Vérifie que resolve_club_and_org inclut les ententes associées."""

    @pytest.mark.asyncio
    async def test_entente_included_in_resolved(self, patch_get_client, mock_client):
        """Quand on cherche 'Gerzat Basket', l'entente ENT. GERZAT / JULES VERNE
        doit être incluse dans les clubs résolus."""
        from ffbb_mcp.services import resolve_club_and_org

        call_count = {"n": 0}

        async def mock_search(nom, limit=20):
            call_count["n"] += 1
            nom_up = nom.upper()
            if "BASKET" in nom_up:
                return [{"id": 1001, "nom": "GERZAT BASKET", "code": ""}]
            # Secondary search for key word "GERZAT"
            return [
                {"id": 1001, "nom": "GERZAT BASKET", "code": ""},
                {"id": 1002, "nom": "ENT. GERZAT / JULES VERNE", "code": ""},
            ]

        org_mock = MagicMock()
        org_mock.nom = "GERZAT BASKET"
        org_mock.id = 1001
        org_mock.code = ""
        org_mock.model_dump = MagicMock(
            return_value={"nom": "GERZAT BASKET", "id": 1001, "code": ""}
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        import ffbb_mcp.services as svc

        original = svc.search_organismes_service
        svc.search_organismes_service = mock_search
        try:
            resolved, _ = await resolve_club_and_org(
                club_name="Gerzat Basket",
                organisme_id=None,
                categorie=None,
            )
        finally:
            svc.search_organismes_service = original

        org_ids = [str(r["organisme_id"]) for r in resolved]
        assert "1001" in org_ids, "Main club should be resolved"
        assert "1002" in org_ids, "Entente ENT. GERZAT / JULES VERNE should be included"
        assert call_count["n"] == 2, (
            "Both primary and secondary searches should be called"
        )

    @pytest.mark.asyncio
    async def test_non_entente_excluded_from_secondary(
        self, patch_get_client, mock_client
    ):
        """Les clubs sans 'ENT.' dans le nom ne doivent pas être ajoutés via la
        recherche secondaire (éviter les faux positifs)."""
        from ffbb_mcp.services import resolve_club_and_org

        async def mock_search(nom, limit=20):
            nom_up = nom.upper()
            if "BASKET" in nom_up:
                return [{"id": 1001, "nom": "GERZAT BASKET", "code": ""}]
            return [
                {"id": 1001, "nom": "GERZAT BASKET", "code": ""},
                {"id": 1003, "nom": "GERZAT SPORT", "code": ""},  # no ENT.
            ]

        org_mock = MagicMock()
        org_mock.nom = "GERZAT BASKET"
        org_mock.id = 1001
        org_mock.code = ""
        org_mock.model_dump = MagicMock(
            return_value={"nom": "GERZAT BASKET", "id": 1001, "code": ""}
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        import ffbb_mcp.services as svc

        original = svc.search_organismes_service
        svc.search_organismes_service = mock_search
        try:
            resolved, _ = await resolve_club_and_org(
                club_name="Gerzat Basket",
                organisme_id=None,
                categorie=None,
            )
        finally:
            svc.search_organismes_service = original

        org_ids = [str(r["organisme_id"]) for r in resolved]
        assert "1001" in org_ids
        assert "1003" not in org_ids, (
            "Non-entente should NOT be added via secondary search"
        )

    @pytest.mark.asyncio
    async def test_no_secondary_search_when_no_key_word(
        self, patch_get_client, mock_client
    ):
        """Si aucun mot distinctif n'est extrait, la recherche secondaire ne doit
        pas être déclenchée (ex : nom d'un seul mot non générique)."""
        from ffbb_mcp.services import resolve_club_and_org

        call_count = {"n": 0}

        async def mock_search(nom, limit=20):
            call_count["n"] += 1
            return [{"id": 9999, "nom": "VILLEURBANNE", "code": ""}]

        org_mock = MagicMock()
        org_mock.nom = "VILLEURBANNE"
        org_mock.id = 9999
        org_mock.code = ""
        org_mock.model_dump = MagicMock(
            return_value={"nom": "VILLEURBANNE", "id": 9999, "code": ""}
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        import ffbb_mcp.services as svc

        original = svc.search_organismes_service
        svc.search_organismes_service = mock_search
        try:
            resolved, _ = await resolve_club_and_org(
                club_name="Villeurbanne",
                organisme_id=None,
                categorie=None,
            )
        finally:
            svc.search_organismes_service = original

        assert call_count["n"] == 1, "Only one search should be called when no key word"


# Tests for resolve_club_and_org M/F filtering


@pytest.mark.asyncio
async def testresolve_club_and_org_mf_filtering():
    """Vérifie le filtrage M/F (Règle 10) dans resolve_club_and_org."""
    from ffbb_mcp.services import resolve_club_and_org

    mock_search = AsyncMock(
        return_value=[
            {"id": 1, "nom": "Stade Clermontois Basket Féminin"},
            {"id": 2, "nom": "Stade Clermontois Basket Auvergne"},
        ]
    )
    mock_get = AsyncMock(
        return_value={
            "id": 2,
            "nom": "Stade Clermontois Basket Auvergne",
            "engagements": [],
        }
    )

    with (
        patch("ffbb_mcp.services.search_organismes_service", mock_search),
        patch("ffbb_mcp.services.get_organisme_service", mock_get),
    ):
        # Test 1: Catégorie M should filter out "Féminin"
        resolved, _ = await resolve_club_and_org(
            club_name="Stade Clermontois", organisme_id=None, categorie="U11M"
        )
        assert len(resolved) == 1
        assert resolved[0]["organisme_id"] == 2

        # Test 2: Catégorie F should filter out the M counterpart (or select Féminin)
        mock_get_f = AsyncMock(
            return_value={
                "id": 1,
                "nom": "Stade Clermontois Basket Féminin",
                "engagements": [],
            }
        )
        with patch("ffbb_mcp.services.get_organisme_service", mock_get_f):
            resolved_f, _ = await resolve_club_and_org(
                club_name="Stade Clermontois", organisme_id=None, categorie="U11F"
            )
            assert len(resolved_f) == 1
            assert resolved_f[0]["organisme_id"] == 1


@pytest.mark.asyncio
async def test_dedupe_inflight_counts_one_miss(monkeypatch):
    misses: list[str] = []
    hits: list[str] = []
    monkeypatch.setattr(services, "_cache_miss_hook", misses.append)
    monkeypatch.setattr(services, "_cache_hit_hook", hits.append)

    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        return {"ok": True}

    cache = TTLCache(maxsize=8, ttl=60)
    inflight: dict[str, asyncio.Task] = {}

    result = await services._dedupe_inflight(
        cache=cache,
        cache_key="k",
        inflight_map=inflight,
        make_coro=fetch,
        cache_name="test",
    )

    assert result == {"ok": True}
    assert calls == 1
    assert misses == ["test"]


# ---------------------------------------------------------------------------
# Tests — Multi-phase auto-resolution (ffbb_resolve_team)
# ---------------------------------------------------------------------------


class TestMultiPhaseResolution:
    """Tests pour la déduplication et le tri des phases dans ffbb_resolve_team."""

    def test_phase_sort_key_poule(self):
        """Phase de poule simple : (0, phase_num, niveau)."""
        e = {"competition": "Départementale U13 - Phase 2", "niveau": 2}
        assert _phase_sort_key(e) == (0, 2, 2)

    def test_phase_sort_key_elimination(self):
        """Phase éliminatoire : (1, phase_num, niveau)."""
        e = {"competition": "U13M-D1 - 1/2 Finales", "niveau": 1}
        assert _phase_sort_key(e) == (1, 1, 1)

    def test_deduplicate_same_team_phases_single(self):
        """Un seul candidat → retour inchangé."""
        candidates = [{"nom_equipe": "U13M", "competition": "Phase 1", "niveau": 1}]
        result = _deduplicate_same_team_phases(candidates)
        assert len(result) == 1
        assert result[0]["nom_equipe"] == "U13M"

    def test_deduplicate_same_team_phases_multi_same_name(self):
        """Même nom_equipe, phases différentes → retourne uniquement la phase la plus avancée."""
        candidates = [
            {
                "nom_equipe": "U13M",
                "competition": "Départementale U13 - Phase 1",
                "niveau": 1,
            },
            {
                "nom_equipe": "U13M",
                "competition": "Départementale U13 - Phase 2",
                "niveau": 2,
            },
            {
                "nom_equipe": "U13M",
                "competition": "Départementale U13 - Phase 3",
                "niveau": 3,
            },
            {"nom_equipe": "U13M", "competition": "U13M-D1 - 1/2 Finales", "niveau": 1},
        ]
        result = _deduplicate_same_team_phases(candidates)
        assert len(result) == 1
        # La phase éliminatoire doit être prioritaire
        assert "1/2 Finales" in result[0]["competition"]

    def test_deduplicate_same_team_phases_multi_different_names(self):
        """Noms différents → pas de déduplication."""
        candidates = [
            {"nom_equipe": "U13M", "competition": "Phase 1", "niveau": 1},
            {"nom_equipe": "U13F", "competition": "Phase 1", "niveau": 1},
        ]
        result = _deduplicate_same_team_phases(candidates)
        assert len(result) == 2

    def test_deduplicate_uses_team_label_fallback(self):
        """Quand nom_equipe est absent, utilise team_label."""
        candidates = [
            {"team_label": "U13M", "competition": "Phase 1", "niveau": 1},
            {"team_label": "U13M", "competition": "Phase 3", "niveau": 3},
        ]
        result = _deduplicate_same_team_phases(candidates)
        assert len(result) == 1
        assert "Phase 3" in result[0]["competition"]

    @pytest.mark.asyncio
    async def test_resolve_team_same_team_multi_phases(
        self, patch_get_client, mock_client
    ):
        """4 candidats même équipe, phases différentes → status resolved, team = phase la plus avancée."""
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 100,
                "nom": "Stade Clermontois",
                "engagements": [
                    {
                        "id": "eng1",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "Départementale U13 - Phase 1",
                            "id": "c1",
                            "sexe": "M",
                            "categorie": {"code": "U13"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "p1"},
                    },
                    {
                        "id": "eng2",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "Départementale U13 - Phase 2",
                            "id": "c2",
                            "sexe": "M",
                            "categorie": {"code": "U13"},
                            "competition_origine_niveau": 2,
                        },
                        "idPoule": {"id": "p2"},
                    },
                    {
                        "id": "eng3",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "Départementale U13 - Phase 3",
                            "id": "c3",
                            "sexe": "M",
                            "categorie": {"code": "U13"},
                            "competition_origine_niveau": 3,
                        },
                        "idPoule": {"id": "p3"},
                    },
                    {
                        "id": "eng4",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "U13M-D1 - 1/2 Finales",
                            "id": "c4",
                            "sexe": "M",
                            "categorie": {"code": "U13"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "p4"},
                    },
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        result = await ffbb_resolve_team_service(
            organisme_id=100,
            club_name=None,
            categorie="U13M1",
        )

        assert result["status"] == "resolved"
        assert result["team"] is not None
        # La phase éliminatoire doit être sélectionnée
        assert "1/2 Finales" in result["team"]["competition"]

    @pytest.mark.asyncio
    async def test_resolve_team_elimination_preferred_over_poule(
        self, patch_get_client, mock_client
    ):
        """Phase éliminatoire sélectionnée en priorité sur phase de poule."""
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 200,
                "nom": "Club Test",
                "engagements": [
                    {
                        "id": "eng_poule",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "Régionale U15 - Phase 3",
                            "id": "cp",
                            "sexe": "M",
                            "categorie": {"code": "U15"},
                            "competition_origine_niveau": 3,
                        },
                        "idPoule": {"id": "pp"},
                    },
                    {
                        "id": "eng_elim",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "U15M - Quart de finale",
                            "id": "ce",
                            "sexe": "M",
                            "categorie": {"code": "U15"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "pe"},
                    },
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        result = await ffbb_resolve_team_service(
            organisme_id=200,
            club_name=None,
            categorie="U15M1",
        )

        assert result["status"] == "resolved"
        assert "Quart de finale" in result["team"]["competition"]

    @pytest.mark.asyncio
    async def test_resolve_team_truly_different_teams_stays_ambiguous(
        self, patch_get_client, mock_client
    ):
        """2 candidats numero_equipe différents et nom_equipe différents → status ambiguous."""
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 300,
                "nom": "Club Multi",
                "engagements": [
                    {
                        "id": "eng1",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "U11M",
                            "id": "c1",
                            "sexe": "M",
                            "categorie": {"code": "U11"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "p1"},
                    },
                    {
                        "id": "eng2",
                        "numeroEquipe": "2",
                        "idCompetition": {
                            "nom": "U11M",
                            "id": "c1",
                            "sexe": "M",
                            "categorie": {"code": "U11"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "p2"},
                    },
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        result = await ffbb_resolve_team_service(
            organisme_id=300,
            club_name=None,
            categorie="U11M",
        )

        # Équipes réellement différentes (numéros 1 et 2) → ambiguous
        assert result["status"] == "ambiguous"
        assert result["team"] is None


class TestSalleEnrichment:
    @pytest.mark.asyncio
    async def test_enrich_salle_data_with_meilisearch(
        self, patch_get_client, mock_client
    ):
        from ffbb_mcp.services.salle import _enrich_salle_data_with_meilisearch

        salle_data = {
            "id": "salle123",
            "libelle": "Gymnase Test",
            "adresse": "1 rue du Test",
        }

        # Mock Commune
        commune_mock = MagicMock()
        commune_mock.libelle = "PARIS"
        commune_mock.code_postal = "75001"

        # Mock Hit
        hit_mock = MagicMock()
        hit_mock.id = "salle123"
        hit_mock.commune = commune_mock

        # Mock Search Result
        search_res_mock = MagicMock()
        search_res_mock.hits = [hit_mock]

        mock_client.search_salles_async = AsyncMock(return_value=search_res_mock)

        await _enrich_salle_data_with_meilisearch(salle_data, mock_client)

        assert salle_data["ville"] == "PARIS"
        assert salle_data["code_postal"] == "75001"


class TestResolveClubAndOrgCache:
    """Vérifie le fonctionnement du cache sur resolve_club_and_org."""

    @pytest.mark.asyncio
    async def testresolve_club_and_org_uses_cache(self, patch_get_client, mock_client):
        from unittest.mock import AsyncMock, MagicMock

        from ffbb_mcp._state import reset_service_state
        from ffbb_mcp.services import resolve_club_and_org

        reset_service_state()
        call_count = {"n": 0}

        async def mock_search(nom, limit=20):
            call_count["n"] += 1
            return [{"id": 1001, "nom": "GERZAT BASKET", "code": "123"}]

        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={"nom": "GERZAT BASKET", "id": 1001, "code": "123"}
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        import ffbb_mcp.services as svc

        original = svc.search_organismes_service
        svc.search_organismes_service = mock_search

        try:
            # Premier appel -> cache miss, recherche (recherche principale + recherche mot-clé)
            resolved1, _ = await resolve_club_and_org(
                club_name="Gerzat Basket",
                organisme_id=None,
                categorie=None,
            )
            assert call_count["n"] == 2

            # Deuxième appel -> cache hit, pas de recherche supplémentaire
            resolved2, _ = await resolve_club_and_org(
                club_name="Gerzat Basket",
                organisme_id=None,
                categorie=None,
            )
            assert call_count["n"] == 2
            assert resolved1 == resolved2

            # Vérification du deepcopy : modifier resolved2 ne doit pas modifier resolved1
            resolved2[0]["nom"] = "MUTATED"
            assert resolved1[0]["nom"] == "GERZAT BASKET"

        finally:
            svc.search_organismes_service = original


class TestBilanSortingByAge:
    """Vérifie que les phases du bilan d'un club sont triées de la plus jeune catégorie aux Seniors."""

    @pytest.mark.asyncio
    async def test_bilan_sorting_by_age(self, patch_get_client, mock_client):
        from unittest.mock import AsyncMock, MagicMock

        from ffbb_mcp._state import reset_service_state
        from ffbb_mcp.services import ffbb_bilan_service

        reset_service_state()

        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 100,
                "nom": "Club Test",
                "engagements": [
                    {
                        "id": "eng_senior",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "Seniors Masculins - Division 1",
                            "id": "c_senior",
                            "sexe": "M",
                            "categorie": {"code": "SENIOR"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "1001"},
                    },
                    {
                        "id": "eng_u11",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "U11 Masculins",
                            "id": "c_u11",
                            "sexe": "M",
                            "categorie": {"code": "U11"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "1002"},
                    },
                    {
                        "id": "eng_u15",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "U15 Féminines",
                            "id": "c_u15",
                            "sexe": "F",
                            "categorie": {"code": "U15"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "1003"},
                    },
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        # Mocks pour get_poule_async
        def make_poule_mock(poule_id, eng_id):
            pm = MagicMock()
            pm.model_dump = MagicMock(
                return_value={
                    "id": poule_id,
                    "rencontres": [],
                    "classements": [
                        {
                            "id_engagement": {"id": eng_id, "numero_equipe": "1"},
                            "organisme_id": "100",
                            "position": 1,
                            "match_joues": 1,
                            "gagnes": 1,
                            "perdus": 0,
                            "nuls": 0,
                            "paniers_marques": 50,
                            "paniers_encaisses": 40,
                            "difference": 10,
                        }
                    ],
                }
            )
            return pm

        poule_senior = make_poule_mock("1001", "eng_senior")
        poule_u11 = make_poule_mock("1002", "eng_u11")
        poule_u15 = make_poule_mock("1003", "eng_u15")

        async def get_poule_side_effect(poule_id):
            p_id = str(poule_id)
            mapping = {
                "1001": poule_senior,
                "1002": poule_u11,
                "1003": poule_u15,
            }
            return mapping.get(p_id)

        mock_client.get_poule_async = AsyncMock(side_effect=get_poule_side_effect)

        result = await ffbb_bilan_service(organisme_id=100)

        # Vérifier que les phases sont triées U11 -> U15 -> Seniors
        phases = result["phases"]
        assert len(phases) == 3
        assert "U11" in phases[0]["competition"]
        assert "U15" in phases[1]["competition"]
        assert "Seniors" in phases[2]["competition"]

        # Vérifier competitions_incluses
        comps = result["competitions_incluses"]
        assert len(comps) == 3
        assert "U11" in comps[0]
        assert "U15" in comps[1]
        assert "Seniors" in comps[2]


class TestBilanEliminatoireTeamAssignment:
    """Vérifie qu'une phase éliminatoire sans classement est correctement attribuée à la bonne équipe."""

    @pytest.mark.asyncio
    async def test_eliminatoire_assigned_to_correct_team(
        self, patch_get_client, mock_client
    ):
        from unittest.mock import AsyncMock, MagicMock

        from ffbb_mcp._state import reset_service_state
        from ffbb_mcp.services import ffbb_bilan_service

        reset_service_state()

        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={
                "id": 100,
                "nom": "Club Test",
                "engagements": [
                    {
                        "id": "eng_u15_eq1",
                        "numeroEquipe": "1",
                        "idCompetition": {
                            "nom": "U15 Féminines Phase 1",
                            "id": "c_u15_1",
                            "sexe": "F",
                            "categorie": {"code": "U15"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "1001"},
                    },
                    {
                        "id": "eng_u15_eq2",
                        "numeroEquipe": "2",
                        "idCompetition": {
                            "nom": "U15 Féminines Finale",
                            "id": "c_u15_2",
                            "sexe": "F",
                            "categorie": {"code": "U15"},
                            "competition_origine_niveau": 1,
                        },
                        "idPoule": {"id": "1002"},
                    },
                ],
            }
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        # La poule 1001 de l'équipe 1 a un classement
        poule_1001 = MagicMock()
        poule_1001.model_dump = MagicMock(
            return_value={
                "id": "1001",
                "rencontres": [],
                "classements": [
                    {
                        "id_engagement": {"id": "eng_u15_eq1", "numero_equipe": "1"},
                        "organisme_id": "100",
                        "position": 2,
                        "match_joues": 2,
                        "gagnes": 1,
                        "perdus": 1,
                        "nuls": 0,
                        "paniers_marques": 80,
                        "paniers_encaisses": 80,
                        "difference": 0,
                    }
                ],
            }
        )

        # La poule 1002 (finale) de l'équipe 2 n'a PAS de classement, mais des rencontres
        poule_1002 = MagicMock()
        poule_1002.model_dump = MagicMock(
            return_value={
                "id": "1002",
                "classements": [],
                "rencontres": [
                    {
                        "id": "m1",
                        "joue": 1,
                        "date_rencontre": "2026-05-15",
                        "nomEquipe1": "Club Test",
                        "nomEquipe2": "Adversaire",
                        "idEngagementEquipe1": {"id": "eng_u15_eq2"},
                        "idEngagementEquipe2": {"id": "eng_other"},
                        "resultatEquipe1": 60,
                        "resultatEquipe2": 50,
                        "numeroJournee": 1,
                    }
                ],
            }
        )

        async def get_poule_side_effect(poule_id):
            p_id = str(poule_id)
            mapping = {
                "1001": poule_1001,
                "1002": poule_1002,
            }
            return mapping.get(p_id)

        mock_client.get_poule_async = AsyncMock(side_effect=get_poule_side_effect)

        result = await ffbb_bilan_service(organisme_id=100)

        # On vérifie que la phase de finale (sans classement, donc issue de rencontres)
        # est bien attribuée à l'équipe 2 !
        equipes = result["equipes_bilan"]
        assert "1" in equipes
        assert "2" in equipes

        eq1_phases = equipes["1"]["phases"]
        eq2_phases = equipes["2"]["phases"]

        assert len(eq1_phases) == 1
        assert eq1_phases[0]["poule_id"] == "1001"

        assert len(eq2_phases) == 1
        assert eq2_phases[0]["poule_id"] == "1002"
        assert eq2_phases[0]["competition"] == "U15 Féminines Finale"


class TestServicesRobustness:
    """Vérifie la robustesse des signatures (arguments positionnels, kwargs supplémentaires, imports)."""

    def test_import_resolve_team_from_club(self):
        from ffbb_mcp.services.club import ffbb_resolve_team_service

        assert callable(ffbb_resolve_team_service)

    @pytest.mark.asyncio
    async def test_positional_and_kwargs_support(self, patch_get_client, mock_client):
        from ffbb_mcp.services import (
            ffbb_bilan_service,
            ffbb_last_result_service,
            ffbb_next_match_service,
            ffbb_resolve_team_service,
            ffbb_saison_bilan_service,
            get_calendrier_club_service,
        )

        # Mock pour get_organisme_async
        org_mock = MagicMock()
        org_mock.model_dump = MagicMock(
            return_value={"nom": "TEST CLUB", "engagements": []}
        )
        mock_client.get_organisme_async = AsyncMock(return_value=org_mock)

        # 1. ffbb_resolve_team_service positionnel + kwargs
        res = await ffbb_resolve_team_service(
            "TEST CLUB", 123, "RM1", extra_param="ignored"
        )
        assert isinstance(res, dict)

        # 2. ffbb_bilan_service positionnel + kwargs
        res = await ffbb_bilan_service(
            "TEST CLUB", 123, "RM1", False, extra_param="ignored"
        )
        assert isinstance(res, dict)

        # 3. ffbb_next_match_service positionnel + kwargs
        res = await ffbb_next_match_service(
            "TEST CLUB", 123, "RM1", 1, False, extra_param="ignored"
        )
        assert isinstance(res, dict)

        # 4. ffbb_last_result_service positionnel + kwargs
        res = await ffbb_last_result_service(
            "TEST CLUB", 123, "RM1", 1, False, extra_param="ignored"
        )
        assert isinstance(res, dict)

        # 5. ffbb_saison_bilan_service positionnel + kwargs
        res = await ffbb_saison_bilan_service(
            "TEST CLUB", 123, "RM1", 1, False, extra_param="ignored"
        )
        assert isinstance(res, dict)

        # 6. get_calendrier_club_service positionnel + kwargs
        res = await get_calendrier_club_service(
            "TEST CLUB", 123, "RM1", 1, extra_param="ignored"
        )
        assert isinstance(res, list)

    @pytest.mark.asyncio
    async def test_get_classement_service_fallback_rencontres(
        self, patch_get_client, mock_client
    ):
        from ffbb_mcp.services.poule import ffbb_get_classement_service

        mock_poule = MagicMock()
        mock_poule.model_dump = MagicMock(
            return_value={
                "id": "100",
                "classements": [],
                "rencontres": [
                    {
                        "nomEquipe1": "TEAM A",
                        "nomEquipe2": "TEAM B",
                        "idOrganisme": "123",
                    },
                    {
                        "nomEquipe1": "TEAM C",
                        "nomEquipe2": "TEAM A",
                        "idOrganisme": "456",
                    },
                ],
            }
        )
        mock_client.get_poule_async = AsyncMock(return_value=mock_poule)

        res = await ffbb_get_classement_service(
            poule_id=100, force_refresh=True, target_organisme_id=123
        )
        assert len(res) == 3
        team_names = [r["equipe"] for r in res]
        assert "TEAM A" in team_names
        assert "TEAM B" in team_names
        assert "TEAM C" in team_names
        assert all(r["status"] == "non_commence" for r in res)
        assert all(r["match_joues"] == 0 for r in res)
        team_a = next(r for r in res if r["equipe"] == "TEAM A")
        assert team_a["is_target"] is True
