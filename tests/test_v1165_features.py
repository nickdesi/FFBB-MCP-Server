"""Tests pour les correctifs et améliorations de la v1.16.5.

Couvre :
1. Warning fraîcheur pour ffbb_search(type="rencontres") et fallback commune dans _lighten_rencontre_hit
2. Resserrement du label 'dominante' pour les petites poules (<= 6 équipes)
3. Présentation enrichie de ffbb_get(salle) (libelle, libelle2, adresse formattée)
4. Absence d'injection cache_hit: False par défaut dans _freshness_meta
5. Enveloppe standardisée pour ffbb_lives et bloc presentation pour not_found / ambiguous
6. Enrichissement salle / lieu dans next_match de find_team_candidates
7. Alias points_marques et points_encaisses dans BilanTotal et PhaseBilan
"""

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.analytics import compute_poule_advanced_stats
from ffbb_mcp.models import BilanTotal, PhaseBilan
from ffbb_mcp.services.common import _freshness_meta
from ffbb_mcp.services.search import _lighten_rencontre_hit, ffbb_search_service
from ffbb_mcp.tools.system import _build_default_get_presentation, ffbb_get_lives


def test_points_marques_alias_in_models():
    """Vérifie que points_marques et points_encaisses sont bien synchronisés."""
    bilan = BilanTotal(paniers_marques=85, paniers_encaisses=72, difference=13)
    assert bilan.points_marques == 85
    assert bilan.points_encaisses == 72
    assert bilan.paniers_marques == 85

    phase = PhaseBilan(
        competition="Départementale",
        poule_id="1234",
        paniers_marques=550,
        paniers_encaisses=480,
    )
    assert phase.points_marques == 550
    assert phase.points_encaisses == 480


def test_style_petites_poules_not_dominante_for_rank_2():
    """Dans une poule de 4 équipes, le 2e en attaque et défense est 'équilibrée', pas 'dominante'."""
    poule_4_teams = {
        "classements": [
            {
                "id_engagement": {"id": "1"},
                "nom_equipe": "Équipe 1",
                "match_joues": 3,
                "paniers_marques": 240,
                "paniers_encaisses": 150,
                "position": 1,
            },
            {
                "id_engagement": {"id": "2"},
                "nom_equipe": "Équipe 2",
                "match_joues": 3,
                "paniers_marques": 200,
                "paniers_encaisses": 180,
                "position": 2,
            },
            {
                "id_engagement": {"id": "3"},
                "nom_equipe": "Équipe 3",
                "match_joues": 3,
                "paniers_marques": 160,
                "paniers_encaisses": 210,
                "position": 3,
            },
            {
                "id_engagement": {"id": "4"},
                "nom_equipe": "Équipe 4",
                "match_joues": 3,
                "paniers_marques": 120,
                "paniers_encaisses": 250,
                "position": 4,
            },
        ],
        "rencontres": [],
    }

    # Équipe 2 (rang 2 att, rang 2 def sur 4 équipes) -> doit être Équipe équilibrée
    stats_eq2 = compute_poule_advanced_stats(poule_4_teams, target_eng_id="2")
    assert "équilibrée" in stats_eq2["style_de_jeu"]
    assert "dominante" not in stats_eq2["style_de_jeu"]
    assert "disclaimer_terminologie" in stats_eq2

    # Équipe 1 (rang 1 att, rang 1 def sur 4 équipes) -> Complète & dominante
    stats_eq1 = compute_poule_advanced_stats(poule_4_teams, target_eng_id="1")
    assert "dominante" in stats_eq1["style_de_jeu"]


def test_freshness_meta_no_spurious_cache_hit_false():
    """_freshness_meta ne doit pas forcer cache_hit=False si non spécifié."""
    meta = _freshness_meta(cache="poule", force_refresh_supported=True)
    assert "cache_hit" not in meta
    assert "stale" not in meta

    # Si explicitement passé, il doit être présent
    meta_hit = _freshness_meta(cache="poule", cache_hit=True)
    assert meta_hit.get("cache_hit") is True


def test_salle_presentation_enriched():
    """Vérifie l'enrichissement libelle/libelle2 et adresse pour ffbb_get(salle)."""
    salle_data = {
        "id": "100",
        "libelle": "FRANCISQUE SAUZEDDE",
        "libelle2": "Maison des Sports",
        "adresse_formatee": "115 avenue Léo Lagrange, 63300 Thiers",
        "ville": "Thiers",
    }
    pres = _build_default_get_presentation("salle", "100", salle_data)
    assert "Maison des Sports (FRANCISQUE SAUZEDDE)" in pres["short_answer"]
    assert "115 avenue Léo Lagrange, 63300 Thiers" in pres["detail_line"]


def test_lighten_rencontre_hit_fallback_commune_from_address():
    """Si la commune n'est pas structurée dans la salle Meilisearch, fallback depuis l'adresse."""
    hit = {
        "id": "r1",
        "salle": {
            "id": "s1",
            "libelle": "Gymnase Jean Mince",
            "adresse": "Rue des Martyrs, 63300 Thiers",
            "commune": None,
        },
    }
    cleaned = _lighten_rencontre_hit(hit)
    salle_clean = cleaned["salle"]
    assert salle_clean["commune"] is not None
    assert salle_clean["commune"]["libelle"] == "Thiers"
    assert salle_clean["commune"]["codePostal"] == "63300"


@pytest.mark.asyncio
async def test_search_rencontres_warning():
    """ffbb_search(type='rencontres') doit inclure un warning sur le cache Meilisearch."""
    with patch(
        "ffbb_mcp.services.search.search_rencontres_service",
        new_callable=AsyncMock,
        return_value=[{"id": "match1", "nom": "Match Test"}],
    ):
        res = await ffbb_search_service(type="rencontres", query="Thiers vs Gerzat")
        assert isinstance(res, dict)
        assert "warning" in res
        assert "Meilisearch" in res["warning"]
        assert "ffbb_next_match" in res["warning"]
        assert "_meta" in res


@pytest.mark.asyncio
async def test_ffbb_lives_standard_envelope():
    """ffbb_lives doit retourner une enveloppe standardisée avec status, count, presentation, provenance."""
    fake_lives = [{"id": "live1", "nomEquipe1": "A", "nomEquipe2": "B"}]
    with (
        patch(
            "ffbb_mcp.server.get_lives_service",
            new_callable=AsyncMock,
            return_value=fake_lives,
        ),
        patch(
            "ffbb_mcp.tools.system.get_lives_service",
            new_callable=AsyncMock,
            return_value=fake_lives,
        ),
    ):
        res = await ffbb_get_lives()
        assert isinstance(res, dict)
        assert res["status"] == "ok"
        assert res["count"] == 1
        assert "items" in res
        assert "presentation" in res
        assert "provenance" in res
        assert "1 match(s)" in res["presentation"]["short_answer"]


@pytest.mark.asyncio
async def test_find_team_candidates_enriches_next_match_salle():
    """find_team_candidates doit enrichir next_match avec le lieu et la salle."""
    from ffbb_mcp.services.team_resolver import ffbb_find_team_candidates_service

    fake_teams = [
        {
            "team_id": "t1",
            "engagement_id": "e1",
            "team_label": "U18M1",
            "categorie": "U18",
            "sexe": "M",
            "competition": "Départementale",
            "poule_id": "p1",
            "nom_equipe": "THIERS - 1",
            "numero_equipe": "1",
        }
    ]
    fake_match = {
        "id": "m1",
        "date_rencontre": "2026-10-11",
        "heure": "10h00",
        "nomEquipe1": "THIERS - 1",
        "nomEquipe2": "GERZAT",
        "idEngagementEquipe1": "e1",
        "idEngagementEquipe2": "e2",
    }
    fake_rencontre_detail = {
        "id": "m1",
        "idSalle": "s1",
        "nomSalle": "Maison des Sports",
    }
    with (
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service",
            new_callable=AsyncMock,
            return_value=fake_teams,
        ),
        patch(
            "ffbb_mcp.services.search.resolve_club_and_org",
            new_callable=AsyncMock,
            return_value=(
                [{"id": "9328", "nom": "THIERS", "organisme_id": "9328"}],
                {},
            ),
        ),
        patch(
            "ffbb_mcp.services.club._fetch_poule_matches",
            new_callable=AsyncMock,
            return_value=[(fake_match, fake_teams[0])],
        ),
        patch(
            "ffbb_mcp.services._fetch_poule_matches",
            new_callable=AsyncMock,
            return_value=[(fake_match, fake_teams[0])],
        ),
        patch(
            "ffbb_mcp.services.search.get_rencontre_service",
            new_callable=AsyncMock,
            return_value=fake_rencontre_detail,
        ),
    ):
        res = await ffbb_find_team_candidates_service(
            club_name="Thiers", categorie="U18M"
        )
        c = res["candidates"][0]
        assert c["next_match"]["lieu"] == "Maison des Sports"
        assert c["next_match"]["salle"] == "Maison des Sports"
