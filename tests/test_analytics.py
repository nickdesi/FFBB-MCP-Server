"""Tests unitaires pour le module analytics et face-à-face (H2H)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.analytics import compute_head_to_head, compute_poule_advanced_stats
from ffbb_mcp.services.club import ffbb_head_to_head_service


def test_compute_poule_advanced_stats():
    """Vérifie le calcul des rangs d'attaque/défense, styles et clutch index."""
    poule_data = {
        "classements": [
            {
                "position": 1,
                "nom_equipe": "STADE CLERMONTOIS",
                "id_engagement": {"id": "100"},
                "match_joues": 10,
                "paniers_marques": 850,  # 85.0 pts/m (1er attaque)
                "paniers_encaisses": 650,  # 65.0 pts/m (1er defense)
            },
            {
                "position": 2,
                "nom_equipe": "ASVEL BASKET",
                "id_engagement": {"id": "200"},
                "match_joues": 10,
                "paniers_marques": 780,  # 78.0 pts/m (2e attaque)
                "paniers_encaisses": 720,  # 72.0 pts/m (2e defense)
            },
        ],
        "rencontres": [
            # Match 1 : Domicile victoire 85-82 (clutch : écart 3)
            {
                "joue": 1,
                "nomEquipe1": "STADE CLERMONTOIS",
                "nomEquipe2": "ASVEL BASKET",
                "resultatEquipe1": 85,
                "resultatEquipe2": 82,
                "idEngagementEquipe1": {"id": "100"},
                "idEngagementEquipe2": {"id": "200"},
            },
            # Match 2 : Extérieur victoire 80-60
            {
                "joue": 1,
                "nomEquipe1": "ASVEL BASKET",
                "nomEquipe2": "STADE CLERMONTOIS",
                "resultatEquipe1": 60,
                "resultatEquipe2": 80,
                "idEngagementEquipe1": {"id": "200"},
                "idEngagementEquipe2": {"id": "100"},
            },
        ],
    }

    stats = compute_poule_advanced_stats(
        poule_data, target_eng_id="100", club_nom="Stade Clermontois"
    )
    assert stats["rang_attaque"] == "1/2"
    assert stats["rang_defense"] == "1/2"
    assert stats["moyenne_points_marques"] == 85.0
    assert stats["moyenne_points_encaisses"] == 65.0
    assert "Complète & dominante" in stats["style_de_jeu"]
    assert stats["domicile"]["victoires"] == 1
    assert stats["exterieur"]["victoires"] == 1
    assert stats["clutch_index"]["matchs_serres_joues"] == 1
    assert stats["clutch_index"]["victoires_serrees"] == 1
    assert stats["clutch_index"]["taux_reussite_clutch"] == 100.0


def test_compute_head_to_head_empty():
    """Vérifie le H2H sans rencontres directes."""
    res = compute_head_to_head(
        [], eng_id_a="100", nom_a="SCBA", eng_id_b="200", nom_b="VICHY"
    )
    assert res["confrontations_count"] == 0
    assert "Aucune confrontation" in res["bilan_h2h"]


def test_compute_head_to_head_with_matches():
    """Vérifie le calcul H2H entre 2 équipes avec victoires partagées."""
    rencontres = [
        {
            "joue": 1,
            "date_rencontre": "2026-01-10",
            "nomEquipe1": "STADE CLERMONTOIS",
            "nomEquipe2": "JA VICHY",
            "resultatEquipe1": 80,
            "resultatEquipe2": 70,
            "idEngagementEquipe1": {"id": "100"},
            "idEngagementEquipe2": {"id": "200"},
            "nomSalle": "Maison des Sports",
        },
        {
            "joue": 1,
            "date_rencontre": "2026-02-20",
            "nomEquipe1": "JA VICHY",
            "nomEquipe2": "STADE CLERMONTOIS",
            "resultatEquipe1": 75,
            "resultatEquipe2": 72,
            "idEngagementEquipe1": {"id": "200"},
            "idEngagementEquipe2": {"id": "100"},
            "nomSalle": "Palais des Sports",
        },
    ]

    h2h = compute_head_to_head(
        rencontres,
        eng_id_a="100",
        nom_a="Stade Clermontois",
        eng_id_b="200",
        nom_b="JA Vichy",
    )
    assert h2h["confrontations_count"] == 2
    assert h2h["victoires_a"] == 1
    assert h2h["victoires_b"] == 1
    assert "Égalité parfaite" in h2h["bilan_h2h"]
    assert h2h["moyenne_points_a"] == 76.0  # (80 + 72) / 2 = 76.0
    assert h2h["moyenne_points_b"] == 72.5  # (70 + 75) / 2 = 72.5
    assert h2h["diff_total"] == 7  # 152 - 145 = 7


@pytest.mark.asyncio
async def test_ffbb_head_to_head_service():
    """Vérifie l'orchestration du service ffbb_head_to_head_service."""
    with (
        patch("ffbb_mcp.services.club._resolve_team_equipes") as mock_resolve,
        patch(
            "ffbb_mcp.services.poule.get_poule_service", new_callable=AsyncMock
        ) as mock_poule,
    ):
        mock_resolve.side_effect = [
            (None, [{"poule_id": "P1", "engagement_id": "E1"}], {"nom": "SCBA"}),
            (None, [{"poule_id": "P1", "engagement_id": "E2"}], {"nom": "VICHY"}),
        ]
        mock_poule.return_value = {
            "classements": [],
            "rencontres": [
                {
                    "joue": 1,
                    "nomEquipe1": "SCBA",
                    "nomEquipe2": "VICHY",
                    "resultatEquipe1": 85,
                    "resultatEquipe2": 70,
                    "idEngagementEquipe1": {"id": "E1"},
                    "idEngagementEquipe2": {"id": "E2"},
                }
            ],
        }

        res = await ffbb_head_to_head_service(
            club_a="SCBA", club_b="VICHY", categorie="SEM1"
        )
        assert res["status"] == "ok"
        assert res["face_a_face"]["victoires_a"] == 1
        assert res["face_a_face"]["victoires_b"] == 0
        assert "Avantage SCBA" in res["face_a_face"]["bilan_h2h"]
        assert len(res["points_cles_llm"]) >= 1
