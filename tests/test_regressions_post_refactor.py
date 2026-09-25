"""Tests de régression pour les 4 anomalies identifiées lors des tests réels."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from ffbb_mcp.dynamique import compute_team_dynamique
from ffbb_mcp.presentation import build_match_presentation, evaluate_round_reliability
from ffbb_mcp.services.team_resolver import ffbb_find_team_candidates_service
from ffbb_mcp.tools.system import _build_default_get_presentation


@pytest.mark.asyncio
async def test_find_team_candidates_preserves_target_team_and_opponent():
    """BUG #1: Vérifie que l'équipe cible et l'adversaire CTC ne sont pas inversés."""
    fake_club = {"organisme_id": 9220, "nom": "JEANNE D'ARC DE VICHY"}
    fake_team = {
        "engagement_id": "200000005346860",
        "team_label": "U13F",
        "nom_equipe": "JEANNE D'ARC DE VICHY",
        "competition": "RFU13 Brassage",
        "competition_type": "PLAT",
        "niveau": "Régional",
        "numero_equipe": 1,
        "poule_id": "200000003056266",
    }
    fake_match = {
        "date_rencontre": "2026-10-10",
        "heure": "13:30",
        "nomEquipe1": "IE - CTC CLERMONT SUD GERGOVIE BASKET - BB COURNON D'AUVERGNE",
        "nomEquipe2": "JEANNE D'ARC DE VICHY",
        "idEngagementEquipe1": {"id": "999999999"},
        "idEngagementEquipe2": {"id": "200000005346860"},
        "resultatEquipe1": None,
        "resultatEquipe2": None,
        "nomSalle": "Salle Polyvalente",
    }

    with (
        patch(
            "ffbb_mcp.services.search.resolve_club_and_org",
            AsyncMock(return_value=([fake_club], fake_club)),
        ),
        patch(
            "ffbb_mcp.services.ffbb_equipes_club_service",
            AsyncMock(return_value=[fake_team]),
        ),
        patch(
            "ffbb_mcp.services._fetch_poule_matches",
            AsyncMock(return_value=[(fake_match, {})]),
        ),
    ):
        res = await ffbb_find_team_candidates_service(
            club_name="JA Vichy",
            categorie="U13F1",
            include_next_match=True,
        )

        assert res["status"] in ("resolved", "ambiguous")
        assert len(res["candidates"]) == 1
        cand = res["candidates"][0]

        # L'équipe candidate doit être Vichy, PAS l'adversaire Clermont Sud
        assert "VICHY" in cand["nom_equipe"].upper()
        assert "CLERMONT SUD" not in cand["nom_equipe"].upper()

        # Le prochain match doit désigner Clermont Sud comme adversaire à l'extérieur
        nxt = cand["next_match"]
        assert nxt is not None
        assert "CLERMONT SUD" in nxt["adversaire"].upper()
        assert nxt["domicile_exterieur"] == "extérieur"


def test_match_presentation_score_order_on_defeat():
    """BUG #2: Vérifie que l'ordre des scores en cas de défaite est 'score_cible à score_adversaire'."""
    dt = datetime(2026, 9, 20, 15, 30, tzinfo=ZoneInfo("Europe/Paris"))
    r_info = evaluate_round_reliability(1)

    # Vichy (domicile: 34) vs Issoire (extérieur: 63)
    p_loss = build_match_presentation(
        team_name="Jeanne D'arc de Vichy",
        opponent_name="US Issoire",
        is_home=True,
        status="final",
        dt_obj=dt,
        time_confirmed=True,
        home_score=34,
        away_score=63,
        round_info=r_info,
        is_last_result=True,
    )

    # Doit afficher 34 à 63 (score de l'équipe cible en premier) et non 63 à 34
    assert "34 à 63" in p_loss.short_answer
    assert "63 à 34" not in p_loss.short_answer
    assert "s'est incliné" in p_loss.short_answer


def test_dynamique_tendance_consistency_few_matches():
    """BUG #3: Vérifie que la tendance est 'Stable ➡️' sur un historique insuffisant (< 3 matchs)."""
    # 1 match joué, 1 défaite
    rencontres = [
        {
            "joue": 1,
            "date_rencontre": "2026-09-20",
            "nomEquipe1": "JEANNE D'ARC DE VICHY",
            "nomEquipe2": "US ISSOIRE",
            "resultatEquipe1": 34,
            "resultatEquipe2": 63,
            "idEngagementEquipe1": {"id": "200000005346860"},
            "idEngagementEquipe2": {"id": "200000005346861"},
        }
    ]

    # Avec ratio_global fourni (comme dans ffbb_bilan)
    res_bilan = compute_team_dynamique(
        rencontres,
        eng_ids={"200000005346860"},
        club_nom="JEANNE D'ARC DE VICHY",
        ratio_global_victoires=0.0,
    )
    assert res_bilan["tendance"] == "Stable ➡️"

    # Sans ratio_global fourni (comme dans ffbb_head_to_head)
    res_h2h = compute_team_dynamique(
        rencontres,
        eng_ids={"200000005346860"},
        club_nom="JEANNE D'ARC DE VICHY",
        ratio_global_victoires=None,
    )
    # Les deux outils doivent être strictement alignés
    assert res_h2h["tendance"] == res_bilan["tendance"]
    assert res_h2h["tendance"] == "Stable ➡️"


def test_ffbb_get_competition_with_club_presentation():
    """BUG #4: Vérifie que le libellé texte de ffbb_get affiche le nom et la poule résolue."""
    data = {
        "status": "found",
        "poule_id": "200000003056266",
        "poule_nom": "Poule A",
        "competition_id": "200000002898047",
        "competition_nom": "RFU13 Brassage",
        "club": "JEANNE D'ARC DE VICHY",
    }
    pres = _build_default_get_presentation(
        type_name="competition",
        resource_id="200000002898047",
        data=data,
    )

    assert "RFU13 Brassage" in pres["short_answer"]
    assert "Poule A" in pres["short_answer"]
    assert "0 poule(s)" not in pres["short_answer"]
    assert "200000003056266" in pres["detail_line"]
