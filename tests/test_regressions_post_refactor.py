"""Tests de régression pour les 4 anomalies identifiées lors des tests réels."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
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
    """BUG #2: Vérifie que l'ordre des scores suit la convention FFBB (domicile puis extérieur)."""
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

    # Convention FFBB : domicile (34) puis extérieur (63)
    assert "34 à 63" in p_loss.short_answer
    assert "63 à 34" not in p_loss.short_answer
    assert "s'est incliné" in p_loss.short_answer


def test_match_presentation_score_order_away_team_home_first():
    """BUG #2 (convention domicile-first): équipe cible à l'extérieur, score affiché domicile puis extérieur."""
    dt = datetime(2026, 9, 20, 15, 30, tzinfo=ZoneInfo("Europe/Paris"))
    r_info = evaluate_round_reliability(1)

    # Cible à l'extérieur (55) battue par le domicile (70) : affichage "70 à 55"
    p_loss_away = build_match_presentation(
        team_name="JA Vichy",
        opponent_name="US Issoire",
        is_home=False,
        status="final",
        dt_obj=dt,
        time_confirmed=True,
        home_score=70,
        away_score=55,
        round_info=r_info,
        is_last_result=True,
    )

    assert "70 à 55" in p_loss_away.short_answer
    assert "55 à 70" not in p_loss_away.short_answer
    assert "s'est incliné" in p_loss_away.short_answer


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


@pytest.mark.asyncio
async def test_ffbb_club_classement_resolves_poule_via_engagement_id():
    """BUG #5: ffbb_club(action='classement') doit résoudre la poule depuis le seul engagement_id."""
    from ffbb_mcp.server import ffbb_club

    eng = MagicMock()
    eng.idOrganisme = 9220
    eng.idPoule = 200000003056266
    eng.numeroEquipe = 1
    eng_client = MagicMock()
    eng_client.get_engagement_async = AsyncMock(return_value=eng)

    mock_classement = AsyncMock(
        return_value=[{"position": 23, "equipe": "JEANNE D'ARC DE VICHY"}]
    )

    with (
        patch(
            "ffbb_mcp.client.FFBBClientFactory.get_client_async",
            new_callable=AsyncMock,
            return_value=eng_client,
        ),
        patch(
            "ffbb_mcp.server.ffbb_get_classement_service",
            mock_classement,
        ),
    ):
        res = await ffbb_club(
            action="classement",
            engagement_id="200000005346860",
        )

    mock_classement.assert_called_once_with(
        poule_id="200000003056266",
        force_refresh=False,
        target_organisme_id="9220",
        target_num=None,
    )
    assert res == [{"position": 23, "equipe": "JEANNE D'ARC DE VICHY"}]


@pytest.mark.asyncio
async def test_ffbb_club_classement_unknown_engagement_returns_error():
    """BUG #5: engagement_id introuvable → erreur explicite, sans crash."""
    from ffbb_mcp.server import ffbb_club

    eng_client = MagicMock()
    eng_client.get_engagement_async = AsyncMock(return_value=None)

    with patch(
        "ffbb_mcp.client.FFBBClientFactory.get_client_async",
        new_callable=AsyncMock,
        return_value=eng_client,
    ):
        res = await ffbb_club(
            action="classement",
            engagement_id="000000000000000",
        )

    assert isinstance(res, list)
    assert "200000003056266" not in str(res)
    assert "engagement_id" in res[0]["error"]
    assert "equipes" in res[0]["error"]


@pytest.mark.asyncio
async def test_ffbb_club_equipes_resolves_org_via_engagement_id():
    """BUG #5 (sweep): ffbb_club(action='equipes') doit accepter le seul engagement_id."""
    from ffbb_mcp.server import ffbb_club

    eng = MagicMock()
    eng.idOrganisme = 9220
    eng.idPoule = 200000003056266
    eng.numeroEquipe = 1
    eng_client = MagicMock()
    eng_client.get_engagement_async = AsyncMock(return_value=eng)

    fake_equipes = [
        {"engagement_id": "200000005346860", "nom_equipe": "JEANNE D'ARC DE VICHY"}
    ]
    mock_equipes = AsyncMock(return_value=fake_equipes)

    with (
        patch(
            "ffbb_mcp.client.FFBBClientFactory.get_client_async",
            new_callable=AsyncMock,
            return_value=eng_client,
        ),
        patch(
            "ffbb_mcp.server.ffbb_equipes_club_service",
            mock_equipes,
        ),
    ):
        res = await ffbb_club(
            action="equipes",
            engagement_id="200000005346860",
        )

    mock_equipes.assert_called_once_with(
        organisme_id="9220",
        filtre=None,
        org_data=None,
        force_refresh=False,
    )
    assert res == fake_equipes


@pytest.mark.asyncio
async def test_ffbb_club_equipes_threads_resolved_org_data():
    """Opti: ffbb_club(action='equipes') réutilise l'org_data déjà résolu (1 fetch évité)."""
    from ffbb_mcp.server import ffbb_club

    fake_org_data = {
        "nom": "JEANNE D'ARC DE VICHY",
        "engagements": [{"id": "200000005346860"}],
    }
    mock_resolve = AsyncMock(
        return_value=(
            [{"organisme_id": 9220, "nom": "JEANNE D'ARC DE VICHY"}],
            fake_org_data,
        )
    )
    fake_equipes = [{"engagement_id": "200000005346860"}]
    mock_equipes = AsyncMock(return_value=fake_equipes)

    with (
        patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.server.ffbb_equipes_club_service", mock_equipes),
    ):
        res = await ffbb_club(action="equipes", club_name="JA Vichy")

    mock_equipes.assert_called_once_with(
        organisme_id=9220,
        filtre=None,
        org_data=fake_org_data,
        force_refresh=False,
    )
    assert res == fake_equipes


@pytest.mark.asyncio
async def test_ffbb_club_equipes_no_threading_on_force_refresh():
    """Opti: force_refresh=True → pas de réutilisation d'org_data (fraîcheur exigée)."""
    from ffbb_mcp.server import ffbb_club

    fake_org_data = {"nom": "JA Vichy", "engagements": []}
    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": 9220, "nom": "JA Vichy"}], fake_org_data)
    )
    mock_equipes = AsyncMock(return_value=[{"engagement_id": "1"}])

    with (
        patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.server.ffbb_equipes_club_service", mock_equipes),
    ):
        await ffbb_club(action="equipes", club_name="JA Vichy", force_refresh=True)

    mock_equipes.assert_called_once_with(
        organisme_id=9220,
        filtre=None,
        org_data=None,
        force_refresh=True,
    )


@pytest.mark.asyncio
async def test_resolve_engagement_refs_handles_scalar_and_dict_ids():
    """Opti: le helper partagé normalise ids scalaires et dicts {"id": ...}."""
    from ffbb_mcp.services.common import resolve_engagement_refs

    eng = MagicMock()
    eng.idOrganisme = {"id": "9220"}
    eng.idPoule = "200000003056266"
    eng.idCompetition = {"id": "200000002898047"}
    eng.numeroEquipe = 2
    eng_client = MagicMock()
    eng_client.get_engagement_async = AsyncMock(return_value=eng)

    with patch(
        "ffbb_mcp.client.FFBBClientFactory.get_client_async",
        new_callable=AsyncMock,
        return_value=eng_client,
    ):
        refs = await resolve_engagement_refs("200000005346860")

    assert refs == {
        "organisme_id": "9220",
        "poule_id": "200000003056266",
        "competition_id": {"id": "200000002898047"},
        "numero_equipe": 2,
    }

    eng_client.get_engagement_async = AsyncMock(return_value=None)
    with patch(
        "ffbb_mcp.client.FFBBClientFactory.get_client_async",
        new_callable=AsyncMock,
        return_value=eng_client,
    ):
        missing = await resolve_engagement_refs("000000000000000")

    assert missing == {
        "organisme_id": None,
        "poule_id": None,
        "competition_id": None,
        "numero_equipe": None,
    }
