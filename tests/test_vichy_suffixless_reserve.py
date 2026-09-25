"""Non-régression : outils singuliers sur équipe réserve sans suffixe FFBB natif.

Contexte : JEANNE D'ARC DE VICHY (organisme_id=9220) engage deux U15M sans
suffixe -1/-2 natif (``numero_equipe == ""``), départagées par hiérarchie de
division (RMU15 Brassage régional = fanion, Départementale = réserve).

Bug résiduel corrigé ici : ``ffbb_resolve_team`` résolvait correctement la
réserve, mais ``ffbb_next_match``/``ffbb_last_result`` perdaient ses matchs
en aval car ``_match_team_name(..., numero=2)`` exige un suffixe "- 2" que
les noms de rencontres FFBB ne portent pas pour ces équipes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import ffbb_mcp.services as svc
import ffbb_mcp.services.club as club_mod
import ffbb_mcp.services.salle as salle_mod
import ffbb_mcp.services.search as search_mod
from ffbb_mcp.services.club import ffbb_last_result_service, ffbb_next_match_service

VICHY_TEAMS = [
    {
        "engagement_id": "200000005347050",
        "team_id": "200000005347050",
        "poule_id": "p1",
        "competition_id": "c1",
        "competition": "RMU15 Brassage",
        "competition_code": "RMU15",
        "competition_type": "PLAT",
        "team_label": "U15M",
        "nom_equipe": "JEANNE D'ARC DE VICHY",
        "numero_equipe": "",
        "categorie": "U15",
        "sexe": "M",
    },
    {
        "engagement_id": "200000005358356",
        "team_id": "200000005358356",
        "poule_id": "p2",
        "competition_id": "c2",
        "competition": "Départementale masculine U15",
        "competition_code": "DMU15",
        "competition_type": "DIV",
        "team_label": "U15M",
        "nom_equipe": "JEANNE D'ARC DE VICHY",
        "numero_equipe": "",
        "categorie": "U15",
        "sexe": "M",
    },
]


def _scheduled_match(mid: str, adversaire: str) -> dict:
    return {
        "id": mid,
        "nomEquipe1": "JEANNE D'ARC DE VICHY",
        "nomEquipe2": adversaire,
        "date_rencontre": "2026-09-27 10:00:00",
        "numeroJournee": 1,
        "joue": 0,
        "idEngagementEquipe1": None,
        "idEngagementEquipe2": None,
    }


@pytest.fixture
def mock_vichy_poules(monkeypatch):
    """Chemin complet mocké : résolution réelle, poules avec rencontres sans suffixe ni IDs d'engagement."""

    async def mock_resolve(
        club_name=None, organisme_id=None, categorie=None, force_refresh=False
    ):
        return ([{"organisme_id": "9220", "nom": "JEANNE D'ARC DE VICHY"}], None)

    async def mock_equipes(
        organisme_id=None,
        filtre=None,
        org_data=None,
        force_refresh=False,
        season_id=None,
    ):
        return [dict(t) for t in VICHY_TEAMS]

    async def mock_poule(pid, force_refresh=False):
        adv = "BC GANNAT" if str(pid) == "p2" else "STADE CLERMONTOIS"
        return {"id": str(pid), "rencontres": [_scheduled_match(f"m_{pid}", adv)]}

    monkeypatch.setattr(search_mod, "resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(club_mod, "resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(club_mod, "ffbb_equipes_club_service", mock_equipes)
    monkeypatch.setattr(svc, "get_poule_service", AsyncMock(side_effect=mock_poule))
    monkeypatch.setattr(search_mod, "get_rencontre_service", AsyncMock(return_value={}))
    monkeypatch.setattr(
        salle_mod, "_enrich_with_salle_details", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        club_mod, "get_client_async", AsyncMock(return_value=AsyncMock())
    )


@pytest.mark.asyncio
async def test_next_match_vichy_reserve_numero_2(mock_vichy_poules):
    """ffbb_next_match(9220, U15M, 2) retrouve le match vs BC GANNAT (poule p2)."""
    res = await ffbb_next_match_service(
        organisme_id="9220", categorie="U15M", numero_equipe=2
    )

    assert res["status"] == "ok"
    assert res["match"]["poule_id"] == "p2"
    assert res["match"]["match_id"] == "m_p2"
    assert res["match"]["adversaire"] == "BC GANNAT"
    assert str(res["match"]["date"]).startswith("2026-09-27")
    assert (
        res["provenance"]["technical"]["resource_ids"]["engagement_id"]
        == "200000005358356"
    )


@pytest.mark.asyncio
async def test_next_match_vichy_fanion_numero_1(mock_vichy_poules):
    """Le cas équipe 1 continue de fonctionner (poule p1, autre adversaire)."""
    res = await ffbb_next_match_service(
        organisme_id="9220", categorie="U15M", numero_equipe=1
    )

    assert res["status"] == "ok"
    assert res["match"]["poule_id"] == "p1"
    assert res["match"]["adversaire"] == "STADE CLERMONTOIS"
    assert (
        res["provenance"]["technical"]["resource_ids"]["engagement_id"]
        == "200000005347050"
    )


@pytest.mark.asyncio
async def test_last_result_vichy_reserve_domicile(mock_vichy_poules, monkeypatch):
    """La réserve à domicile sous nom sans suffixe : victoire 70-60 bien attribuée."""
    played = {
        "id": "m_p2_played",
        "nomEquipe1": "JEANNE D'ARC DE VICHY",
        "nomEquipe2": "BC GANNAT",
        "resultatEquipe1": 70,
        "resultatEquipe2": 60,
        "date_rencontre": "2026-09-20 15:00:00",
        "numeroJournee": 1,
        "joue": 1,
        "idEngagementEquipe1": None,
        "idEngagementEquipe2": None,
    }

    async def mock_poule_played(pid, force_refresh=False):
        return {"id": str(pid), "rencontres": [dict(played)]}

    monkeypatch.setattr(
        svc, "get_poule_service", AsyncMock(side_effect=mock_poule_played)
    )

    res = await ffbb_last_result_service(
        organisme_id="9220", categorie="U15M", numero_equipe=2
    )

    assert res["status"] == "ok"
    assert res["data"]["match"]["result_for_team"] == "win"
    assert res["score_domicile"] == 70
    assert res["score_exterieur"] == 60
    assert res["victoire"] is True


@pytest.mark.asyncio
async def test_fetch_poule_matches_explicit_number_stays_strict(monkeypatch):
    """Garde-fou : une équipe à numéro natif explicite n'attrape pas les matchs sans suffixe."""
    from ffbb_mcp.services.club import _fetch_poule_matches

    equipe_2 = {
        "engagement_id": "eng2",
        "poule_id": "px",
        "competition": "Départementale masculine U15",
        "team_label": "U15M2",
        "nom_equipe": "CLUB X - 2",
        "numero_equipe": "2",
    }
    poule = {
        "id": "px",
        "rencontres": [
            {
                "id": "m_team1",
                "nomEquipe1": "CLUB X",
                "nomEquipe2": "ADV A",
                "date_rencontre": "2026-09-27 10:00:00",
                "numeroJournee": 1,
                "joue": 0,
                "idEngagementEquipe1": None,
                "idEngagementEquipe2": None,
            },
            {
                "id": "m_team2",
                "nomEquipe1": "CLUB X - 2",
                "nomEquipe2": "ADV B",
                "date_rencontre": "2026-09-27 10:00:00",
                "numeroJournee": 1,
                "joue": 0,
                "idEngagementEquipe1": None,
                "idEngagementEquipe2": None,
            },
        ],
    }
    monkeypatch.setattr(svc, "get_poule_service", AsyncMock(return_value=poule))

    matches = await _fetch_poule_matches(
        [equipe_2], organisme_nom="CLUB X", numero_equipe=2
    )

    assert [m["id"] for m, _ in matches] == ["m_team2"]
