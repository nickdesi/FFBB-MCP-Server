"""Tests de validation unitaire et d'intégration pour ffbb_team_summary avec classement compact.

Couvre l'ensemble des critères d'acceptation :
1. 1 seul appel team_summary -> bilan + prochain match + classement compact (cols, rows, target_pos).
2. Économie de tokens (réponse sans logos ni dynamique par défaut < 1500 tokens).
3. Égalité de points (RSG art. 28) : départage 'confrontation' (point-average particulier) vs 'quotient'.
4. Phases multiples : poule courante retournée et autres phases dans 'autres_phases'.
5. Poule non démarrée / incomplète : rows=[], warning 'classement_indisponible'.
6. Équipe réserve (SEM2) et club avec plusieurs équipes seniors.
7. Détection d'incohérence bilan/classement et retry automatique côté serveur avec force_refresh.
8. Enrichissement de presentation.short_answer avec position, points, prochain adversaire, date, heure et lieu.
9. Paramètre include ('bilan', 'last', 'next', 'classement', 'dynamique') et paramètre detail.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.server import ffbb_team_summary
from ffbb_mcp.services.poule import format_compact_classement

# ---------------------------------------------------------------------------
# Fixtures & Données de test
# ---------------------------------------------------------------------------

STADE_CLERMONTOIS_ORG = {
    "organisme_id": 9326,
    "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
}

RESOLVED_SEM1 = {
    "status": "resolved",
    "team": {
        "team_id": 1001,
        "team_label": "SEM1",
        "numero_equipe": "1",
        "nom_equipe": "STADE CLERMONTOIS BASKET AUVERGNE",
        "competition": "Pré-nationale Masculine",
        "engagement_id": "200000005355513",
        "poule_id": "200000003055513",
    },
    "club_resolu": STADE_CLERMONTOIS_ORG,
}

RESOLVED_SEM2 = {
    "status": "resolved",
    "team": {
        "team_id": 1002,
        "team_label": "SEM2",
        "numero_equipe": "2",
        "nom_equipe": "STADE CLERMONTOIS BASKET AUVERGNE - 2",
        "competition": "Régionale 2 Masculine",
        "engagement_id": "200000005355514",
        "poule_id": "200000003055514",
    },
    "club_resolu": STADE_CLERMONTOIS_ORG,
}

BILAN_SEM1 = {
    "status": "ok",
    "bilan_total": {"match_joues": 2, "gagnes": 1, "perdus": 1, "nuls": 0},
    "phase_courante": {
        "competition": "Pré-nationale Masculine",
        "poule_id": "200000003055513",
        "position": 2,
        "match_joues": 2,
    },
    "phases": [
        {
            "competition": "Phase 1 - Brassage",
            "poule_id": "200000003055510",
            "numero_equipe": "1",
            "position": 1,
        },
        {
            "competition": "Pré-nationale Masculine",
            "poule_id": "200000003055513",
            "numero_equipe": "1",
            "position": 2,
        },
    ],
    "dynamique": {
        "forme_str": "V D",
        "serie_actuelle": {"label": "1 défaite"},
    },
}

NEXT_MATCH_SEM1 = {
    "status": "ok",
    "match": {
        "adversaire": "OUEST LYONNAIS BASKET - 2",
        "domicile": True,
        "date": "2026-10-10",
        "heure": "20:00",
        "nomSalle": "Gymnase Honoré Fleury",
        "ville": "Clermont-Ferrand",
    },
    "adversaire": "OUEST LYONNAIS BASKET - 2",
    "domicile": True,
    "date": "2026-10-10",
    "heure": "20:00",
    "nomSalle": "Gymnase Honoré Fleury",
    "ville": "Clermont-Ferrand",
    "presentation": {
        "short_answer": "Stade Clermontois recevra Ouest Lyonnais Basket 2.",
        "detail_line": "Match à domicile programmé samedi 10 octobre à 20 h.",
    },
}

CLASSEMENT_6_EQUIPES = [
    {
        "position": 1,
        "equipe": "OUEST LYONNAIS BASKET - 2",
        "points": 4,
        "match_joues": 2,
        "gagnes": 2,
        "perdus": 0,
        "difference": 49,
        "paniers_marques": 160,
        "paniers_encaisses": 111,
        "is_target": False,
        "organisme_id": "9991",
        "logo_url": "https://api.ffbb.com/assets/logo1",
        "penalites_arbitrage": None,
        "nombre_forfaits": None,
    },
    {
        "position": 2,
        "equipe": "STADE CLERMONTOIS BASKET AUVERGNE",
        "points": 3,
        "match_joues": 2,
        "gagnes": 1,
        "perdus": 1,
        "difference": 12,
        "paniers_marques": 140,
        "paniers_encaisses": 128,
        "is_target": True,
        "organisme_id": "9326",
        "numero_equipe": "1",
        "logo_url": "https://api.ffbb.com/assets/logo2",
        "penalites_arbitrage": None,
        "nombre_forfaits": None,
    },
    {
        "position": 3,
        "equipe": "AL ROANNE",
        "points": 3,
        "match_joues": 2,
        "gagnes": 1,
        "perdus": 1,
        "difference": -5,
        "paniers_marques": 130,
        "paniers_encaisses": 135,
        "is_target": False,
        "organisme_id": "9993",
    },
    {
        "position": 4,
        "equipe": "VAULX-EN-VELIN BASKET CLUB",
        "points": 3,
        "match_joues": 2,
        "gagnes": 1,
        "perdus": 1,
        "difference": -15,
        "paniers_marques": 120,
        "paniers_encaisses": 135,
        "is_target": False,
        "organisme_id": "9994",
    },
    {
        "position": 5,
        "equipe": "BRON BASKET CLUB",
        "points": 3,
        "match_joues": 2,
        "gagnes": 1,
        "perdus": 1,
        "difference": -18,
        "paniers_marques": 115,
        "paniers_encaisses": 133,
        "is_target": False,
        "organisme_id": "9995",
    },
    {
        "position": 6,
        "equipe": "BASKET CLUB COMMUNAY TERNAY",
        "points": 2,
        "match_joues": 2,
        "gagnes": 0,
        "perdus": 2,
        "difference": -23,
        "paniers_marques": 110,
        "paniers_encaisses": 133,
        "is_target": False,
        "organisme_id": "9996",
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_summary_1_call_next_match_and_classement_6_equipes():
    """Critère 1 : 1 seul appel team_summary renvoie prochain match + classement 6 équipes compact."""
    mock_resolve = AsyncMock(return_value=RESOLVED_SEM1)
    mock_bilan = AsyncMock(return_value=BILAN_SEM1)
    mock_last = AsyncMock(return_value=None)
    mock_next = AsyncMock(return_value=NEXT_MATCH_SEM1)
    mock_classement = AsyncMock(return_value=CLASSEMENT_6_EQUIPES)
    mock_poule = AsyncMock(return_value={"id": 200000003055513, "rencontres": []})

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
        patch("ffbb_mcp.server.get_poule_service", mock_poule),
    ):
        res = await ffbb_team_summary(
            club_name="Stade Clermontois",
            categorie="SEM1",
        )

        assert res["status"] == "ok"
        # Prochain match présent
        assert res["next_match"] is not None
        assert res["next_match"]["adversaire"] == "OUEST LYONNAIS BASKET - 2"

        # Classement compact présent avec 6 équipes
        assert "classement" in res
        cl = res["classement"]
        assert cl["cols"] == ["pos", "equipe", "pts", "j", "g", "p", "pm", "pe", "diff"]
        assert len(cl["rows"]) == 6
        assert cl["target_pos"] == 2
        # Équipe cible en position 2
        target_row = cl["rows"][1]
        assert target_row[0] == 2
        assert "STADE CLERMONTOIS" in target_row[1]
        assert target_row[2] == 3  # pts
        assert target_row[6] == 140  # pm
        assert target_row[7] == 128  # pe
        assert target_row[8] == 12  # diff

        # Dynamique absente par défaut
        assert "dynamique" not in res

        # Économie de tokens : charge JSON < 1500 tokens (estimée ~ 4 chars / token)
        raw_json = json.dumps(res, ensure_ascii=False)
        estimated_tokens = len(raw_json) / 4
        assert estimated_tokens < 1500, (
            f"Payload trop volumineux : {estimated_tokens} tokens"
        )


@pytest.mark.asyncio
async def test_team_summary_short_answer_includes_pos_pts_and_next_match():
    """Critère 7 : presentation.short_answer intègre position, points, prochain adversaire, date, heure, lieu."""
    mock_resolve = AsyncMock(return_value=RESOLVED_SEM1)
    mock_bilan = AsyncMock(return_value=BILAN_SEM1)
    mock_last = AsyncMock(return_value=None)
    mock_next = AsyncMock(return_value=NEXT_MATCH_SEM1)
    mock_classement = AsyncMock(return_value=CLASSEMENT_6_EQUIPES)
    mock_poule = AsyncMock(return_value={"id": 200000003055513, "rencontres": []})

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
        patch("ffbb_mcp.server.get_poule_service", mock_poule),
    ):
        res = await ffbb_team_summary(
            club_name="Stade Clermontois",
            categorie="SEM1",
        )

        short_ans = res["presentation"]["short_answer"]
        # Vérification position et points
        assert "2e" in short_ans
        assert "3 pts" in short_ans
        # Bilan V/D
        assert "1 victoire" in short_ans
        assert "1 défaite" in short_ans
        # Prochain adversaire, date, heure et salle
        assert "OUEST LYONNAIS BASKET - 2" in short_ans
        assert "2026-10-10" in short_ans
        assert "20:00" in short_ans
        assert "Gymnase Honoré Fleury" in short_ans


@pytest.mark.asyncio
async def test_tiebreak_rsg_art28_confrontation_vs_quotient():
    """Critère 5.1 : Départage Art. 28 RSG - confrontation directe puis quotient."""
    teams_tied = [
        {
            "position": 1,
            "equipe": "EQUIPE A",
            "points": 4,
            "match_joues": 2,
            "gagnes": 2,
            "perdus": 0,
            "difference": 10,
            "paniers_marques": 150,
            "paniers_encaisses": 140,
        },
        {
            "position": 2,
            "equipe": "EQUIPE B",
            "points": 4,
            "match_joues": 2,
            "gagnes": 2,
            "perdus": 0,
            "difference": 30,
            "paniers_marques": 170,
            "paniers_encaisses": 140,
        },
    ]

    # Cas 1 : Confrontation directe jouée (A a battu B)
    # Même si B a une meilleure différence générale (+30 contre +10),
    # A doit être classé 1er au point-average particulier (Art. 28.2)
    poule_with_h2h = {
        "rencontres": [
            {
                "nomEquipe1": "EQUIPE A",
                "resultatEquipe1": 80,
                "nomEquipe2": "EQUIPE B",
                "resultatEquipe2": 72,
            }
        ]
    }

    res_h2h = format_compact_classement(teams_tied, poule_data=poule_with_h2h)
    assert res_h2h["departage"] == "confrontation"
    assert res_h2h["rows"][0][1] == "EQUIPE A"
    assert res_h2h["rows"][1][1] == "EQUIPE B"

    # Cas 2 : Aucune confrontation directe jouée
    # Départage provisoire à la différence générale : B (+30) devant A (+10)
    poule_no_h2h = {"rencontres": []}
    res_quotient = format_compact_classement(teams_tied, poule_data=poule_no_h2h)
    assert res_quotient["departage"] == "difference_generale"
    assert res_quotient["rows"][0][1] == "EQUIPE B"
    assert res_quotient["rows"][1][1] == "EQUIPE A"


@pytest.mark.asyncio
async def test_multiple_phases_exposes_autres_phases():
    """Critère 5.2 : Multiples phases -> poule courante par défaut et autres_phases listées."""
    mock_resolve = AsyncMock(return_value=RESOLVED_SEM1)
    mock_bilan = AsyncMock(return_value=BILAN_SEM1)
    mock_last = AsyncMock(return_value=None)
    mock_next = AsyncMock(return_value=None)
    mock_classement = AsyncMock(return_value=CLASSEMENT_6_EQUIPES)
    mock_poule = AsyncMock(return_value={"id": 200000003055513, "rencontres": []})

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
        patch("ffbb_mcp.server.get_poule_service", mock_poule),
    ):
        res = await ffbb_team_summary(
            club_name="Stade Clermontois",
            categorie="SEM1",
        )

        assert "autres_phases" in res
        assert len(res["autres_phases"]) == 1
        assert res["autres_phases"][0]["poule_id"] == "200000003055510"
        assert "Phase 1 - Brassage" in res["autres_phases"][0]["label"]
        assert mock_bilan.call_args.kwargs.get("engagement_id") == "200000005355513"
        assert mock_bilan.call_args.kwargs.get("poule_id") == "200000003055513"


@pytest.mark.asyncio
async def test_poule_incomplète_ou_non_demarree_warns_classement_indisponible():
    """Critère 5.3 : Poule vide/non démarrée -> rows=[], warning classement_indisponible, jamais d'omission."""
    mock_resolve = AsyncMock(return_value=RESOLVED_SEM1)
    mock_bilan = AsyncMock(
        return_value={
            "status": "ok",
            "bilan_total": {"match_joues": 0, "gagnes": 0, "perdus": 0},
            "phase_courante": {
                "competition": "Championnat Régional",
                "poule_id": "200000003099999",
            },
        }
    )
    mock_last = AsyncMock(return_value=None)
    mock_next = AsyncMock(return_value=None)
    mock_classement = AsyncMock(return_value=[])  # Aucun classement
    mock_poule = AsyncMock(return_value={"id": 200000003099999, "rencontres": []})

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
        patch("ffbb_mcp.server.get_poule_service", mock_poule),
    ):
        res = await ffbb_team_summary(
            club_name="Stade Clermontois",
            categorie="SEM1",
        )

        assert "classement" in res
        cl = res["classement"]
        assert cl["rows"] == []
        assert cl["target_pos"] is None
        assert "classement_indisponible" in res["presentation"]["warnings"]


@pytest.mark.asyncio
async def test_reserve_team_sem2_resolution():
    """Critère 5.4 : Résolution et classement d'une équipe réserve (SEM2)."""
    mock_resolve = AsyncMock(return_value=RESOLVED_SEM2)
    mock_bilan = AsyncMock(
        return_value={
            "status": "ok",
            "bilan_total": {"match_joues": 1, "gagnes": 1, "perdus": 0},
            "phase_courante": {
                "competition": "Régionale 2 Masculine",
                "poule_id": "200000003055514",
            },
        }
    )
    mock_last = AsyncMock(return_value=None)
    mock_next = AsyncMock(return_value=None)
    mock_classement = AsyncMock(
        return_value=[
            {
                "position": 1,
                "equipe": "STADE CLERMONTOIS BASKET AUVERGNE - 2",
                "points": 2,
                "match_joues": 1,
                "gagnes": 1,
                "perdus": 0,
                "difference": 15,
                "is_target": True,
                "organisme_id": "9326",
                "numero_equipe": "2",
            }
        ]
    )
    mock_poule = AsyncMock(return_value={"id": 200000003055514, "rencontres": []})

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
        patch("ffbb_mcp.server.get_poule_service", mock_poule),
    ):
        res = await ffbb_team_summary(
            club_name="Stade Clermontois",
            categorie="SEM2",
        )

        assert res["team"]["team_label"] == "SEM2"
        assert res["classement"]["target_pos"] == 1
        assert (
            "STADE CLERMONTOIS BASKET AUVERGNE - 2" in res["classement"]["rows"][0][1]
        )


@pytest.mark.asyncio
async def test_coherence_check_and_server_side_retry():
    """Critère 4 : Incohérence bilan/classement -> warning 'incoherence_position' et retry avec force_refresh."""
    # Bilan initial désynchronisé (position=4, match_joues=1)
    bilan_stale = {
        "status": "ok",
        "bilan_total": {"match_joues": 1, "gagnes": 0, "perdus": 1},
        "phase_courante": {
            "competition": "Pré-nationale Masculine",
            "poule_id": "200000003055513",
            "position": 4,  # Divergence avec classement (pos=2)
            "match_joues": 1,  # Divergence avec classement (j=2)
        },
    }

    # Bilan frais après refresh
    bilan_fresh = {
        "status": "ok",
        "bilan_total": {"match_joues": 2, "gagnes": 1, "perdus": 1},
        "phase_courante": {
            "competition": "Pré-nationale Masculine",
            "poule_id": "200000003055513",
            "position": 2,
            "match_joues": 2,
        },
    }

    mock_resolve = AsyncMock(return_value=RESOLVED_SEM1)
    # Premier appel stale, second appel fresh
    mock_bilan = AsyncMock(side_effect=[bilan_stale, bilan_fresh])
    mock_last = AsyncMock(return_value=None)
    mock_next = AsyncMock(return_value=None)
    mock_classement = AsyncMock(return_value=CLASSEMENT_6_EQUIPES)
    mock_poule = AsyncMock(return_value={"id": 200000003055513, "rencontres": []})

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
        patch("ffbb_mcp.server.get_poule_service", mock_poule),
    ):
        res = await ffbb_team_summary(
            club_name="Stade Clermontois",
            categorie="SEM1",
            force_refresh=False,
        )

        # Vérifie que le warning est émis et que le second appel avec force_refresh a eu lieu
        assert "incoherence_position" in res["presentation"]["warnings"]
        assert mock_bilan.await_count == 2
        assert mock_bilan.await_args_list[1].kwargs.get("force_refresh") is True


@pytest.mark.asyncio
async def test_include_parameter_customization_and_dynamique():
    """Critère 1 : Paramètre include contrôle la présence des sections."""
    mock_resolve = AsyncMock(return_value=RESOLVED_SEM1)
    mock_bilan = AsyncMock(return_value=BILAN_SEM1)
    mock_last = AsyncMock(return_value=None)
    mock_next = AsyncMock(return_value=NEXT_MATCH_SEM1)
    mock_classement = AsyncMock(return_value=CLASSEMENT_6_EQUIPES)
    mock_poule = AsyncMock(return_value={"id": 200000003055513, "rencontres": []})

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
        patch("ffbb_mcp.server.get_poule_service", mock_poule),
    ):
        # 1. Demande avec dynamique explicite
        res_with_dyn = await ffbb_team_summary(
            club_name="Stade Clermontois",
            categorie="SEM1",
            include=["bilan", "classement", "dynamique"],
        )
        assert "dynamique" in res_with_dyn
        assert res_with_dyn["dynamique"] is not None
        assert "next_match" in res_with_dyn and res_with_dyn["next_match"] is None

        # 2. Demande classement seul
        res_classement_only = await ffbb_team_summary(
            club_name="Stade Clermontois",
            categorie="SEM1",
            include=["classement"],
        )
        assert "classement" in res_classement_only
        assert "summary" not in res_classement_only


@pytest.mark.asyncio
async def test_detail_parameter_in_compact_classement():
    """Critère 2 : detail=False exclut logos et pénalités nulles, detail=True inclut les colonnes actives."""
    teams = [
        {
            "position": 1,
            "equipe": "TEAM A",
            "points": 4,
            "match_joues": 2,
            "gagnes": 2,
            "perdus": 0,
            "difference": 10,
            "logo_url": "https://api.ffbb.com/assets/logo_a",
            "nombre_forfaits": 1,  # Non nul !
            "penalites_arbitrage": None,
        },
        {
            "position": 2,
            "equipe": "TEAM B",
            "points": 2,
            "match_joues": 2,
            "gagnes": 0,
            "perdus": 2,
            "difference": -10,
            "logo_url": "https://api.ffbb.com/assets/logo_b",
            "nombre_forfaits": 0,
            "penalites_arbitrage": None,
        },
    ]

    # Sans detail : strict cols pos, equipe, pts, j, g, p, pm, pe, diff
    compact = format_compact_classement(teams, detail=False)
    assert compact["cols"] == [
        "pos",
        "equipe",
        "pts",
        "j",
        "g",
        "p",
        "pm",
        "pe",
        "diff",
    ]
    assert len(compact["rows"][0]) == 9

    # Avec detail : 'forfaits' et 'logo_url' actifs car non nuls
    detailed = format_compact_classement(teams, detail=True)
    assert "forfaits" in detailed["cols"]
    assert "logo_url" in detailed["cols"]
    # 'penalites_arbitrage' étant None partout, elle ne pollue pas cols
    assert "penalites_arbitrage" not in detailed["cols"]


def test_incomplete_mini_championship_fallback_general_difference():
    """Vérifie que pour 3+ équipes à égalité avec mini-championnat incomplet,

    le départage s'effectue au point-average général (différence générale)
    conformément à l'Art. 28 du RSG sans biais de mini-championnat partiel.
    Cas réel JA Vichy (+81) vs AL Meyzieu (+72).
    """
    teams_tied = [
        {
            "position": 9,
            "equipe": "JEANNE D'ARC DE VICHY",
            "points": 5,
            "match_joues": 3,
            "gagnes": 2,
            "perdus": 1,
            "paniers_marques": 254,
            "paniers_encaisses": 173,
            "difference": 81,
        },
        {
            "position": 10,
            "equipe": "AL MEYZIEU",
            "points": 5,
            "match_joues": 3,
            "gagnes": 2,
            "perdus": 1,
            "paniers_marques": 280,
            "paniers_encaisses": 208,
            "difference": 72,
        },
        {
            "position": 11,
            "equipe": "AL CALUIRE ET CUIRE",
            "points": 5,
            "match_joues": 3,
            "gagnes": 2,
            "perdus": 1,
            "paniers_marques": 220,
            "paniers_encaisses": 168,
            "difference": 52,
        },
    ]

    # Seulement 1 match joué sur 3 possibles (mini-championnat incomplet) :
    # Meyzieu a battu Caluire, mais Vichy n'a affronté ni l'un ni l'autre
    poule_data = {
        "rencontres": [
            {
                "nomEquipe1": "AL MEYZIEU",
                "resultatEquipe1": 85,
                "nomEquipe2": "AL CALUIRE ET CUIRE",
                "resultatEquipe2": 70,
            }
        ]
    }

    res = format_compact_classement(teams_tied, poule_data=poule_data)
    # Le départage doit se faire au point-average général car le mini-championnat est incomplet
    assert res["departage"] == "difference_generale"
    rows = res["rows"]
    # Vichy (+81) doit rester devant Meyzieu (+72) et Caluire (+52)
    assert rows[0][1] == "JEANNE D'ARC DE VICHY"
    assert rows[1][1] == "AL MEYZIEU"
    assert rows[2][1] == "AL CALUIRE ET CUIRE"


def test_complete_mini_championship_applies_h2h():
    """Pour 3 équipes à égalité avec mini-championnat complet (toutes les paires jouées),

    le mini-championnat Art. 28.3 s'applique aux points particuliers.
    """
    teams_tied = [
        {
            "position": 1,
            "equipe": "EQUIPE A",
            "points": 4,
            "difference": 10,
            "paniers_marques": 100,
        },
        {
            "position": 2,
            "equipe": "EQUIPE B",
            "points": 4,
            "difference": 30,
            "paniers_marques": 120,
        },
        {
            "position": 3,
            "equipe": "EQUIPE C",
            "points": 4,
            "difference": 20,
            "paniers_marques": 110,
        },
    ]

    # Toutes les 3 paires ont joué : A bat B, A bat C, B bat C
    poule_data = {
        "rencontres": [
            {
                "nomEquipe1": "EQUIPE A",
                "resultatEquipe1": 70,
                "nomEquipe2": "EQUIPE B",
                "resultatEquipe2": 60,
            },
            {
                "nomEquipe1": "EQUIPE A",
                "resultatEquipe1": 80,
                "nomEquipe2": "EQUIPE C",
                "resultatEquipe2": 50,
            },
            {
                "nomEquipe1": "EQUIPE B",
                "resultatEquipe1": 65,
                "nomEquipe2": "EQUIPE C",
                "resultatEquipe2": 60,
            },
        ]
    }

    res = format_compact_classement(teams_tied, poule_data=poule_data)
    assert res["departage"] == "confrontation"
    # A (2 victoires dans le mini-chpt) devant B (1 victoire) devant C (0 victoire)
    assert res["rows"][0][1] == "EQUIPE A"
    assert res["rows"][1][1] == "EQUIPE B"
    assert res["rows"][2][1] == "EQUIPE C"


def test_tiebreak_with_identical_diff_applies_quotient():
    """Quand deux équipes ont la même différence de points et pas de confrontation directe,

    le départage relève du quotient général (Art. 28).
    """
    teams_tied = [
        {
            "position": 4,
            "equipe": "CTC CSR01 - SAINT-REMY",
            "points": 6,
            "difference": 71,
            "paniers_marques": 392,
            "paniers_encaisses": 321,
        },
        {
            "position": 5,
            "equipe": "VILLEFRANCHE BEAUJOLAIS",
            "points": 6,
            "difference": 71,
            "paniers_marques": 244,
            "paniers_encaisses": 173,
        },
    ]
    poule_data = {"rencontres": []}
    res = format_compact_classement(teams_tied, poule_data=poule_data)
    assert res["departage"] == "quotient"


@pytest.mark.asyncio
async def test_format_poule_response_numerical_sorting():
    """Vérifie que format_poule_response trie numériquement les classements

    (1, 2, ..., 9, 10, 11...) au lieu du tri lexical de l'API Directus (1, 10, 11, 2...).
    """
    from ffbb_mcp.services.poule import format_poule_response

    poule_data = {
        "id": 12345,
        "libelle": "Poule A",
        "classements": [
            {"position": "1", "id_engagement": {"nom": "EQ 1"}},
            {"position": "10", "id_engagement": {"nom": "EQ 10"}},
            {"position": "11", "id_engagement": {"nom": "EQ 11"}},
            {"position": "2", "id_engagement": {"nom": "EQ 2"}},
            {"position": "9", "id_engagement": {"nom": "EQ 9"}},
        ],
        "rencontres": [],
    }

    formatted = await format_poule_response(poule_data)
    positions = [int(c["position"]) for c in formatted["classements"]]
    assert positions == [1, 2, 9, 10, 11]


@pytest.mark.asyncio
async def test_incompatible_engagement_and_poule_returns_error():
    """P1 : En cas d'incompatibilité entre engagement_id et poule_id,

    ffbb_team_summary doit rejeter avec une erreur structurée sans réponse composite.
    """
    mock_resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "team": {
                "team_id": 999,
                "team_label": "U15M",
                "nom_equipe": "JEANNE D'ARC DE VICHY",
                "competition": "RMU15 Brassage",
                "engagement_id": "200000005347050",
                "poule_id": "200000003056282",  # Poule régionale
            },
            "club_resolu": {"organisme_id": 9220},
        }
    )

    with patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve):
        res = await ffbb_team_summary(
            engagement_id="200000005347050",
            poule_id="200000003057847",  # Poule départementale contradictoire !
            include=["bilan", "next", "classement"],
        )

        assert res["status"] == "error"
        assert res["code"] == "incompatible_identifiers"
        assert "Incompatibilité d'identifiants" in res["error"]
        assert "incompatible_identifiers" in res["warnings"]


@pytest.mark.asyncio
async def test_missing_bilan_does_not_display_zero_wins_zero_losses():
    """P1 : Si le bilan est absent ou vide, ne jamais afficher '0 victoires, 0 défaites'."""
    mock_resolve = AsyncMock(return_value=RESOLVED_SEM1)
    mock_bilan = AsyncMock(
        return_value={"status": "error", "error": "Bilan non calculable"}
    )
    mock_last = AsyncMock(return_value=None)
    mock_next = AsyncMock(return_value=None)
    mock_classement = AsyncMock(return_value=CLASSEMENT_6_EQUIPES)
    mock_poule = AsyncMock(return_value={"id": 200000003055513, "rencontres": []})

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
        patch("ffbb_mcp.server.get_poule_service", mock_poule),
    ):
        res = await ffbb_team_summary(
            engagement_id="200000005355513",
            poule_id="200000003055513",
        )

        short_ans = res["presentation"]["short_answer"]
        assert "0 victoires, 0 défaites" not in short_ans
        assert "non disponible" in short_ans
