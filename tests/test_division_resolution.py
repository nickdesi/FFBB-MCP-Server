"""Tests unitaires pour la résolution des codes de division (NM3, NF1, PNM, etc.)
et la localisation d'équipes/clubs dans les compétitions multi-poules.
"""

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.server import ffbb_club, ffbb_get
from ffbb_mcp.services.club import (
    _filter_teams_by_competition,
    _parse_division_code,
    ffbb_equipes_club_service,
)
from ffbb_mcp.services.poule import find_team_poule_service
from ffbb_mcp.services.search import ffbb_resolve_team_service

# ---------------------------------------------------------------------------
# 1. Tests unitaires pour _parse_division_code
# ---------------------------------------------------------------------------


def test_parse_division_code_nationale():
    assert _parse_division_code("NM3") == ("N", "M", "3")
    assert _parse_division_code("nm3") == ("N", "M", "3")
    assert _parse_division_code("NF1") == ("N", "F", "1")
    assert _parse_division_code("N1M") == ("N", "M", "1")
    assert _parse_division_code("N2F") == ("N", "F", "2")
    assert _parse_division_code("N3") == ("N", None, "3")


def test_parse_division_code_regionale_departementale():
    assert _parse_division_code("PNM") == ("PN", "M", "")
    assert _parse_division_code("PNF") == ("PN", "F", "")
    assert _parse_division_code("PRM") == ("PR", "M", "")
    assert _parse_division_code("PRF") == ("PR", "F", "")
    assert _parse_division_code("R2") == ("R", None, "2")
    assert _parse_division_code("RM2") == ("R", "M", "2")
    assert _parse_division_code("RF1") == ("R", "F", "1")
    assert _parse_division_code("DM3") == ("D", "M", "3")
    assert _parse_division_code("DF2") == ("D", "F", "2")
    assert _parse_division_code("D1") == ("D", None, "1")


def test_parse_division_code_non_divisions():
    # Catégories d'âge classiques ou libellés d'équipe : ne doivent PAS être reconnus comme division
    assert _parse_division_code("U11M") is None
    assert _parse_division_code("U18F") is None
    assert _parse_division_code("SEM1") is None
    assert _parse_division_code("SEF") is None
    assert _parse_division_code("SENIOR") is None
    assert _parse_division_code("") is None
    assert _parse_division_code(None) is None


# ---------------------------------------------------------------------------
# 2. Tests unitaires pour _filter_teams_by_competition
# ---------------------------------------------------------------------------


def test_filter_teams_by_competition_filters_friendly():
    teams = [
        {
            "nom_equipe": "SEM1",
            "competition": "TOURNVOI AMICAL NM3",
            "competition_code": "NM3",
            "competition_type": "PLAT",
        },
        {
            "nom_equipe": "SEM1",
            "competition": "NATIONALE MASCULINE 3",
            "competition_code": "NM3",
            "competition_type": "DIV",
        },
        {
            "nom_equipe": "SEM2",
            "competition": "PRE-REGIONALE MASCULINE",
            "competition_code": "PRM",
            "competition_type": "DIV",
        },
    ]

    # Pour NM3, doit retourner l'engagement officiel DIV, ignorant le match amical/tournoi
    matched = _filter_teams_by_competition(teams, "NM3")
    assert len(matched) == 1
    assert matched[0]["competition_type"] == "DIV"
    assert matched[0]["nom_equipe"] == "SEM1"

    # Pour PRM, doit retourner SEM2
    matched_prm = _filter_teams_by_competition(teams, "PRM")
    assert len(matched_prm) == 1
    assert matched_prm[0]["nom_equipe"] == "SEM2"


def test_filter_teams_by_competition_fallback_amical():
    # S'il n'y a que de l'amical, on le garde faute de mieux
    teams = [
        {
            "nom_equipe": "SEM1",
            "competition": "TOURNVOI AMICAL NM3",
            "competition_code": "NM3",
            "competition_type": "PLAT",
        }
    ]
    matched = _filter_teams_by_competition(teams, "NM3")
    assert len(matched) == 1
    assert matched[0]["nom_equipe"] == "SEM1"


# ---------------------------------------------------------------------------
# 3. Test d'intégration pour ffbb_equipes_club_service avec division
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ffbb_equipes_club_service_division_filter():
    mock_org_data = {
        "id": "200000002677671",
        "nom": "ETOILE DE CHAMALIERES SAYAT",
        "engagements": [
            {
                "id": "eng1",
                "numeroEquipe": "1",
                "idPoule": {
                    "id": "200000003054381",
                    "nom": "POULE H",
                },
                "idCompetition": {
                    "id": "200000002897180",
                    "nom": "NATIONALE MASCULINE 3",
                    "code": "NM3",
                    "typeCompetition": "DIV",
                    "categorie": {"code": "SE"},
                    "sexe": "M",
                },
            },
            {
                "id": "eng2",
                "numeroEquipe": "2",
                "idPoule": {
                    "id": "poule_prm",
                    "nom": "POULE A",
                },
                "idCompetition": {
                    "id": "comp_prm",
                    "nom": "PRE-REGIONALE MASCULINE",
                    "code": "PRM",
                    "typeCompetition": "DIV",
                    "categorie": {"code": "SE"},
                    "sexe": "M",
                },
            },
        ],
    }

    # Test avec org_data direct
    res = await ffbb_equipes_club_service(
        organisme_id="200000002677671",
        filtre="NM3",
        org_data=mock_org_data,
    )
    assert len(res) == 1
    assert res[0]["team_label"] == "SEM1"
    assert res[0]["poule_id"] == "200000003054381"
    assert res[0]["competition_code"] == "NM3"

    # Filtrer par division "PRM"
    res_prm = await ffbb_equipes_club_service(
        organisme_id="200000002677671",
        filtre="PRM",
        org_data=mock_org_data,
    )
    assert len(res_prm) == 1
    assert res[0]["poule_id"] == "200000003054381"
    assert res_prm[0]["team_label"] == "SEM2"

    # Filtrer par division inexistante -> message d'erreur avec suggestions
    res_unknown = await ffbb_equipes_club_service(
        organisme_id="200000002677671",
        filtre="NF1",
        org_data=mock_org_data,
    )
    assert "error" in res_unknown[0]
    assert "suggested_teams" in res_unknown[0]


# ---------------------------------------------------------------------------
# 4. Test pour ffbb_resolve_team_service avec division
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ffbb_resolve_team_service_division(monkeypatch):
    mock_equipe_nm3 = {
        "team_id": "eng1",
        "team_label": "SEM1",
        "nom_equipe": "ETOILE DE CHAMALIERES SAYAT 1",
        "numero_equipe": "1",
        "poule_id": "200000003054381",
        "competition": "NATIONALE MASCULINE 3",
        "competition_code": "NM3",
        "competition_type": "DIV",
        "phase_label": "Poule H",
    }

    mock_resolve = AsyncMock(
        return_value=(
            [{"organisme_id": "200000002677671", "nom": "ETOILE DE CHAMALIERES SAYAT"}],
            None,
        )
    )

    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.ffbb_equipes_club_service",
        AsyncMock(return_value=[mock_equipe_nm3]),
    )

    res = await ffbb_resolve_team_service(
        club_name="Chamalières",
        categorie="NM3",
    )

    assert "error" not in res
    assert res.get("status") == "resolved"
    team = res.get("team", {})
    assert team.get("team_label") == "SEM1"
    assert team.get("poule_id") == "200000003054381"


# ---------------------------------------------------------------------------
# 5. Test pour find_team_poule_service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_team_poule_service_fast_path(monkeypatch):
    """Vérifie le fast-path : résolution directe via les engagements du club."""
    mock_org_data = {
        "id": "200000002677671",
        "nom": "ETOILE DE CHAMALIERES SAYAT",
        "engagements": [
            {
                "numeroEquipe": "1",
                "idPoule": {
                    "id": "200000003054381",
                    "nom": "POULE H",
                },
                "idCompetition": {
                    "id": "200000002897180",
                    "nom": "NATIONALE MASCULINE 3",
                    "categorie": {"code": "SE"},
                    "sexe": "M",
                },
            }
        ],
    }

    mock_resolve = AsyncMock(
        return_value=(
            [{"organisme_id": "200000002677671", "nom": "ETOILE DE CHAMALIERES SAYAT"}],
            mock_org_data,
        )
    )

    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)

    res = await find_team_poule_service(
        competition_id="200000002897180",
        organisme_id_or_name="Chamalières",
    )

    assert res.get("status") == "found"
    assert res.get("poule_id") == "200000003054381"
    assert res.get("poule_nom") == "POULE H"
    assert res.get("team_label") == "SEM1"


@pytest.mark.asyncio
async def test_find_team_poule_service_fallback(monkeypatch):
    """Vérifie le fallback par scan des poules si le fast-path ne donne rien."""
    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_organisme_service",
        AsyncMock(return_value={"id": "9999", "nom": "CLUB TEST", "engagements": []}),
    )

    mock_comp_data = {
        "id": "100",
        "poules": [
            {"id": "101", "nom": "Poule A"},
            {"id": "102", "nom": "Poule B"},
        ],
    }

    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_competition_service",
        AsyncMock(return_value=mock_comp_data),
    )

    async def mock_get_poule(poule_id):
        if str(poule_id) == "102":
            return {
                "id": "102",
                "nom": "Poule B",
                "classements": [
                    {
                        "organisme_id": "9999",
                        "organisme_nom": "CLUB TEST",
                        "id_engagement": {"nom": "CLUB TEST 1"},
                    }
                ],
            }
        return {"id": "101", "nom": "Poule A", "classements": []}

    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_poule_service",
        mock_get_poule,
    )

    res = await find_team_poule_service(
        competition_id="100",
        organisme_id_or_name="9999",
    )

    assert res.get("status") == "found"
    assert res.get("poule_id") == "102"
    assert res.get("poule_nom") == "Poule B"


# ---------------------------------------------------------------------------
# 6. Test pour ffbb_get avec club parameter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ffbb_get_competition_with_club():
    mock_find = AsyncMock(
        return_value={
            "status": "found",
            "poule_id": "200000003054381",
            "poule_nom": "POULE H",
            "team_label": "SEM1",
        }
    )

    with patch("ffbb_mcp.server.find_team_poule_service", mock_find):
        res = await ffbb_get(
            id=200000002897180,
            type="competition",
            club="Chamalières",
        )
        assert res.get("status") == "found"
        assert res.get("poule_id") == "200000003054381"
        mock_find.assert_called_once_with(
            competition_id=200000002897180,
            organisme_id_or_name="Chamalières",
        )


# ---------------------------------------------------------------------------
# 7. Test pour ffbb_club(action="classement", filtre="NM3")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ffbb_club_classement_with_division_filter():
    mock_resolve = AsyncMock(
        return_value=(
            [{"organisme_id": 200000002677671, "nom": "ETOILE DE CHAMALIERES SAYAT"}],
            None,
        )
    )
    mock_resolve_poule = AsyncMock(return_value=200000003054381)
    mock_classement = AsyncMock(
        return_value=[
            {"position": 1, "nom": "CHENÔVE", "is_target": False},
            {"position": 9, "nom": "CHAMALIERES", "is_target": True},
        ]
    )

    with (
        patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.server.resolve_poule_id_service", mock_resolve_poule),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
    ):
        res = await ffbb_club(
            action="classement",
            club_name="Chamalières",
            filtre="NM3",
        )

        mock_resolve.assert_called_once_with(
            club_name="Chamalières",
            organisme_id=None,
            categorie="NM3",
            limit=3,
        )
        mock_resolve_poule.assert_called_once_with(
            200000002677671, "NM3", phase_query=None
        )
        mock_classement.assert_called_once_with(
            poule_id=200000003054381,
            force_refresh=False,
            target_organisme_id=200000002677671,
            target_num=None,
        )
        assert len(res) == 2
        assert res[1]["is_target"] is True


# ---------------------------------------------------------------------------
# 8. Test pour les divisions jeunes (NMU15, RMU15, DMU15)
# ---------------------------------------------------------------------------


def test_filter_teams_by_competition_youth_divisions():
    teams = [
        {
            "team_label": "U15M1",
            "competition": "NATIONALE MASCULINE U15 ELITE",
            "competition_code": "NMU15 ELITE",
            "poule_id": "poule_u15_nat",
        },
        {
            "team_label": "U15M",
            "competition": "RMU15 Brassage",
            "competition_code": "RMU15 Brassage",
            "poule_id": "poule_u15_reg",
        },
        {
            "team_label": "U15M3",
            "competition": "Départementale masculine U15",
            "competition_code": "DMU15",
            "poule_id": "poule_u15_dep",
        },
    ]

    m_nat = _filter_teams_by_competition(teams, "NMU15")
    assert len(m_nat) == 1
    assert m_nat[0]["team_label"] == "U15M1"
    assert m_nat[0]["poule_id"] == "poule_u15_nat"

    m_reg = _filter_teams_by_competition(teams, "RMU15")
    assert len(m_reg) == 1
    assert m_reg[0]["team_label"] == "U15M"
    assert m_reg[0]["poule_id"] == "poule_u15_reg"

    m_dep = _filter_teams_by_competition(teams, "DMU15")
    assert len(m_dep) == 1
    assert m_dep[0]["team_label"] == "U15M3"
    assert m_dep[0]["poule_id"] == "poule_u15_dep"


@pytest.mark.asyncio
async def test_find_team_poule_service_rencontres_fallback(monkeypatch):
    """Vérifie le fallback sur rencontres quand classements est vide (avant J1)."""
    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_organisme_service",
        AsyncMock(
            return_value={"id": "200000000000001", "nom": "CLUB U15", "engagements": []}
        ),
    )

    mock_comp_data = {
        "id": "200",
        "poules": [
            {"id": "201", "nom": "Poule A"},
            {"id": "202", "nom": "Poule B"},
        ],
    }
    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_competition_service",
        AsyncMock(return_value=mock_comp_data),
    )

    async def mock_get_poule(poule_id):
        if str(poule_id) == "202":
            return {
                "id": "202",
                "nom": "Poule B",
                "classements": [],
                "rencontres": [
                    {
                        "nomEquipe1": "CLUB U15 - 1",
                        "nomEquipe2": "ADVERSAIRE - 1",
                    }
                ],
            }
        return {"id": "201", "nom": "Poule A", "classements": [], "rencontres": []}

    monkeypatch.setattr("ffbb_mcp.services.poule.get_poule_service", mock_get_poule)

    res = await find_team_poule_service(
        competition_id="200",
        organisme_id_or_name="200000000000001",
    )

    assert res.get("status") == "found"
    assert res.get("poule_id") == "202"
    assert res.get("poule_nom") == "Poule B"
    assert res.get("team_label") == "CLUB U15 - 1"
