"""Tests unitaires et de non-régression pour les fonctionnalités FFBB MCP v1.16.7."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.presentation import build_match_presentation
from ffbb_mcp.services.bilan import ffbb_saison_bilan_service
from ffbb_mcp.services.calendar import (
    get_calendrier_club_service,
)
from ffbb_mcp.services.club import ffbb_last_result_service
from ffbb_mcp.tools.team import ffbb_bilan, ffbb_bilan_saison, ffbb_team_summary


def test_score_presentation_away_winner_score_first():
    """A4: Le score du vainqueur doit toujours être énoncé en premier, même à l'extérieur."""
    p_away_win = build_match_presentation(
        team_name="Stade Clermontois",
        opponent_name="CTC Bédat Volcans",
        is_home=False,
        status="completed",
        dt_obj=None,
        time_confirmed=True,
        home_score=52,
        away_score=56,
        is_last_result=True,
    )
    assert "a battu CTC Bédat Volcans 56 à 52" in p_away_win.short_answer
    assert "52 à 56" not in p_away_win.short_answer

    p_home_win = build_match_presentation(
        team_name="Stade Clermontois",
        opponent_name="US Beaumont",
        is_home=True,
        status="completed",
        dt_obj=None,
        time_confirmed=True,
        home_score=74,
        away_score=31,
        is_last_result=True,
    )
    assert "a battu US Beaumont 74 à 31" in p_home_win.short_answer


@pytest.mark.asyncio
async def test_last_result_exposes_score_pour_contre_and_diff():
    """A4: ffbb_last_result doit exposer explicitement score_pour, score_contre et diff_points."""
    fake_team = {
        "nom_equipe": "STADE CLERMONTOIS - 2",
        "team_label": "U13M2",
        "numero_equipe": "2",
        "poule_id": "p1",
        "engagement_id": "eng2",
    }
    fake_match = {
        "id": "12345",
        "equipe1": "US Beaumont",
        "equipe2": "STADE CLERMONTOIS - 2",
        "score_equipe1": "52",
        "score_equipe2": "56",
        "nom_equipe1": "US Beaumont",
        "nom_equipe2": "STADE CLERMONTOIS - 2",
        "idEngagementEquipe1": {"id": "eng1"},
        "idEngagementEquipe2": {"id": "eng2"},
        "resultatEquipe1": 52,
        "resultatEquipe2": 56,
        "joue": 1,
        "date_rencontre": "2026-10-03T14:00:00Z",
    }
    with (
        patch(
            "ffbb_mcp.services.club._resolve_team_equipes", new_callable=AsyncMock
        ) as mock_resolve,
        patch(
            "ffbb_mcp.services.club._fetch_poule_matches", new_callable=AsyncMock
        ) as mock_matches,
    ):
        mock_resolve.return_value = (
            None,
            [fake_team],
            {"nom": "STADE CLERMONTOIS", "organisme_id": "9326"},
        )
        mock_matches.return_value = [(fake_match, fake_team)]
        res = await ffbb_last_result_service(
            club_name="Stade Clermontois", categorie="U13M2"
        )
        match_data = res["data"]["match"]
        assert match_data["score_pour"] == 56
        assert match_data["score_contre"] == 52
        assert match_data["diff_points"] == 4


@pytest.mark.asyncio
async def test_calendar_phase_filtering_and_warning():
    """A1: Le filtre de phase dans le calendrier doit filtrer et émettre un warning si aucun match."""
    fake_team = {
        "nom_equipe": "STADE CLERMONTOIS - 2",
        "team_label": "U13M2",
        "numero_equipe": "2",
        "competition": "Départementale masculine U13",
        "poule_id": "p1",
        "engagement_id": "eng2",
    }
    fake_poule = {
        "nom": "Poule Haute 2",
        "competition_nom": "Départementale masculine U13",
        "rencontres": [
            {
                "id": "m1",
                "idEngagementEquipe1": {"id": "eng2"},
                "idEngagementEquipe2": {"id": "eng1"},
                "nomEquipe1": "STADE CLERMONTOIS - 2",
                "nomEquipe2": "US BEAUMONT",
                "resultatEquipe1": 74,
                "resultatEquipe2": 31,
                "joue": 1,
                "date_rencontre": "2026-09-27T14:00:00Z",
            }
        ],
    }
    with (
        patch(
            "ffbb_mcp.services.search.resolve_club_and_org", new_callable=AsyncMock
        ) as mock_resolve,
        patch(
            "ffbb_mcp.services.ffbb_equipes_club_service", new_callable=AsyncMock
        ) as mock_eq,
        patch(
            "ffbb_mcp.services.poule.get_poule_service", new_callable=AsyncMock
        ) as mock_poule,
    ):
        mock_resolve.return_value = (
            [{"nom": "STADE CLERMONTOIS", "organisme_id": "9326"}],
            None,
        )
        mock_eq.return_value = [fake_team]
        mock_poule.return_value = fake_poule

        # Phase 1: match trouvé (Poule Haute 2 est implicitement Phase 1)
        res_p1 = await get_calendrier_club_service(
            club_name="Stade Clermontois",
            organisme_id="9326",
            phase="Phase 1",
            force_refresh=True,
        )
        assert len(res_p1["items"]) == 1

        # Phase 2: 0 match + warning
        res_p2 = await get_calendrier_club_service(
            club_name="Stade Clermontois",
            organisme_id="9326",
            phase="Phase 2",
            force_refresh=True,
        )
        assert len(res_p2["items"]) == 0
        assert res_p2["_meta"]["total"] == 0
        assert any("Phase 2" in w for w in res_p2["presentation"]["warnings"])


@pytest.mark.asyncio
async def test_bilan_saison_ambiguous_when_no_numero_equipe():
    """A2: ffbb_saison_bilan_service avec catégorie sans numéro doit renvoyer ambiguous si plusieurs équipes."""
    fake_teams = [
        {
            "nom_equipe": "STADE CLERMONTOIS - 1",
            "team_label": "U13M1",
            "numero_equipe": "1",
            "competition": "Départementale masculine U13 - Division 10",
            "poule_id": "p1",
            "engagement_id": "eng1",
        },
        {
            "nom_equipe": "STADE CLERMONTOIS - 2",
            "team_label": "U13M2",
            "numero_equipe": "2",
            "competition": "Départementale masculine U13 - Poule Haute 2",
            "poule_id": "p2",
            "engagement_id": "eng2",
        },
    ]
    with (
        patch("ffbb_mcp.services.club.resolve_club_and_org") as mock_org,
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service", new_callable=AsyncMock
        ) as mock_eq,
    ):
        mock_org.return_value = (
            [{"nom": "STADE CLERMONTOIS", "organisme_id": "9326"}],
            None,
        )
        mock_eq.return_value = fake_teams

        # Sans numéro d'équipe explicite -> statut ambiguous
        res = await ffbb_saison_bilan_service(
            club_name="Stade Clermontois",
            categorie="U13M",
            numero_equipe=None,
        )
        assert res.get("status") == "ambiguous"
        assert len(res.get("candidates", [])) == 2


@pytest.mark.asyncio
async def test_bilan_salle_enrichment():
    """A3: dynamique.matchs dans les bilans doit avoir le nom de salle enrichi."""
    fake_teams = [
        {
            "nom_equipe": "STADE CLERMONTOIS - 2",
            "team_label": "U13M2",
            "numero_equipe": "2",
            "competition": "Départementale masculine U13 - Poule Haute 2",
            "poule_id": "p2",
            "engagement_id": "eng2",
        }
    ]
    fake_poule_data = {
        "nom": "Poule Haute 2",
        "classements": [
            {
                "id_engagement": {"id": "eng2"},
                "position": 1,
                "victoires": 2,
                "defaites": 0,
                "nuls": 0,
                "paniers_marques": 130,
                "paniers_encaisses": 83,
            }
        ],
        "rencontres": [
            {
                "id": "match_101",
                "idEngagementEquipe1": {"id": "eng2"},
                "idEngagementEquipe2": {"id": "other_eng"},
                "nomEquipe1": "STADE CLERMONTOIS - 2",
                "nomEquipe2": "US BEAUMONT",
                "resultatEquipe1": 74,
                "resultatEquipe2": 31,
                "joue": 1,
                "date_rencontre": "2026-09-27T14:00:00Z",
                "nomSalle": None,  # salle absente initialement
            }
        ],
    }
    with (
        patch("ffbb_mcp.services.club.resolve_club_and_org") as mock_org,
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service", new_callable=AsyncMock
        ) as mock_eq,
        patch(
            "ffbb_mcp.services.poule.get_poule_service", new_callable=AsyncMock
        ) as mock_poule,
        patch(
            "ffbb_mcp.services.search.get_rencontre_service", new_callable=AsyncMock
        ) as mock_rencontre,
    ):
        mock_org.return_value = (
            [{"nom": "STADE CLERMONTOIS", "organisme_id": "9326"}],
            None,
        )
        mock_eq.return_value = fake_teams
        mock_poule.return_value = fake_poule_data
        mock_rencontre.return_value = {
            "id": "match_101",
            "nomSalle": "Centre Sportif EDITH TAVERT",
        }

        res = await ffbb_saison_bilan_service(
            club_name="Stade Clermontois",
            categorie="U13M2",
            numero_equipe=2,
        )
        assert res.get("status") == "ok"
        matchs = res.get("dynamique", {}).get("matchs", [])
        assert len(matchs) == 1
        assert matchs[0]["salle"] == "Centre Sportif EDITH TAVERT"


def test_tool_docstrings_differentiation():
    """A5: Les docstrings des outils team_summary, bilan_saison et bilan doivent être distinctes."""
    doc_summary = ffbb_team_summary.__doc__ or ""
    doc_saison = ffbb_bilan_saison.__doc__ or ""
    doc_bilan = ffbb_bilan.__doc__ or ""

    assert "Synthèse recommandée" in doc_summary
    assert "multi-phases" in doc_saison
    assert "statistique brut" in doc_bilan
    assert doc_summary != doc_saison
    assert doc_saison != doc_bilan
