from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.services.club import ffbb_match_lookup_service
from ffbb_mcp.services.search import (
    _add_truncation_meta,
    _lighten_rencontre_hit,
    _score_rencontre_relevance,
    _score_salle_relevance,
    ffbb_search_service,
)


def test_lighten_rencontre_hit():
    raw_hit = {
        "id": "match_123",
        "nom_equipe1": "SA THIERS VAILLANTE - 2",
        "nom_equipe2": "GERZAT BASKET",
        "date": "2026-10-11",
        "horaire": "11:00:00",
        "numero_journee": 3,
        "competition_id": {
            "id": "comp_99",
            "nom": "DMU18 - Poule Basse 5",
            "type_competition": "PLAT",
            "autre_champ_lourd": "data",
        },
        "salle": {
            "id": "salle_456",
            "libelle": "Maison des Sports de Thiers",
            "adresse": "Avenue Francisque Sauzedde",
            "commune": {
                "libelle": "Thiers",
                "codePostal": "63300",
                "departement": "Puy-de-Dôme",
                "insee": "63430",
            },
            "capacite": 500,
        },
        "organisateur": {
            "id": 9283,
            "nom": "SA THIERS BASKET",
            "logo": {"url": "https://example.com/logo.png"},
            "contacts": None,
        },
        "officiels": ["Arbitre 1", "Arbitre 2"],
        "thumbnail": "https://example.com/thumb.png",
        "geo": {"lat": 45.8, "lon": 3.5},
        "modification_timestamp": 1791345600000,
        "creation_timestamp": 1780000000000,
        "lower_nom_equipe1": "sa thiers vaillante - 2",
    }

    cleaned = _lighten_rencontre_hit(raw_hit)

    assert cleaned["id"] == "match_123"
    assert cleaned["nom_equipe1"] == "SA THIERS VAILLANTE - 2"
    assert cleaned["nom_equipe2"] == "GERZAT BASKET"
    assert "organisateur" not in cleaned
    assert "officiels" not in cleaned
    assert "thumbnail" not in cleaned
    assert "geo" not in cleaned
    assert "lower_nom_equipe1" not in cleaned
    assert "derniere_mise_a_jour" in cleaned
    assert cleaned["salle"]["commune"]["codePostal"] == "63300"
    assert "autre_champ_lourd" not in cleaned["competition"]


def test_score_salle_relevance():
    salle_thiers = {
        "id": "s1",
        "libelle": "Maison des Sports de Thiers",
        "adresse": "Avenue Francisque Sauzedde",
        "commune": {"libelle": "Thiers", "codePostal": "63300"},
    }
    salle_lyon_rue_thiers = {
        "id": "s2",
        "libelle": "Gymnase Tronchet",
        "adresse": "12 rue Thiers",
        "commune": {"libelle": "Lyon", "codePostal": "69006"},
    }

    score_thiers = _score_salle_relevance(salle_thiers, "Thiers")
    score_lyon = _score_salle_relevance(salle_lyon_rue_thiers, "Thiers")

    assert score_thiers > score_lyon
    assert score_thiers > 150.0
    assert score_lyon < 20.0


def test_score_rencontre_relevance():
    match_u18_thiers_gerzat = {
        "id": "m1",
        "nom_equipe1": "SA THIERS VAILLANTE - 2",
        "nom_equipe2": "GERZAT BASKET",
        "competition": {"nom": "DMU18 - Poule Basse 5"},
    }
    match_u11_thiers_gerzat = {
        "id": "m2",
        "nom_equipe1": "SA THIERS VAILLANTE",
        "nom_equipe2": "GERZAT BASKET",
        "competition": {"nom": "DMU11 - Poule 2"},
    }
    match_normandie_rue_thiers = {
        "id": "m3",
        "nom_equipe1": "CS LILLEBONNE",
        "nom_equipe2": "SPO ROUEN",
        "competition": {"nom": "U18 Régionale"},
        "salle": {"adresse": "Rue Thiers, Lillebonne"},
    }

    query = "Thiers Gerzat U18"
    score_target = _score_rencontre_relevance(match_u18_thiers_gerzat, query)
    score_u11 = _score_rencontre_relevance(match_u11_thiers_gerzat, query)
    score_normandie = _score_rencontre_relevance(match_normandie_rue_thiers, query)

    assert score_target > score_u11
    assert score_target > score_normandie
    assert score_target > 150.0


def test_add_truncation_meta_hint():
    raw = [{"id": 1, "_total_hits": 71}, {"id": 2}]
    res = _add_truncation_meta(raw, limit=20, offset=0)

    meta = res["_meta"]
    assert meta["truncated"] is True
    assert meta["total"] == 71
    assert "hint" in meta
    assert "Affinez votre recherche" in meta["hint"]


@pytest.mark.asyncio
async def test_ffbb_search_service_combines_commune_and_code_postal():
    with patch(
        "ffbb_mcp.services.search._search_generic",
        AsyncMock(return_value=[]),
    ) as mock_generic:
        await ffbb_search_service(
            query="Jean Mince",
            type="salles",
            commune="Thiers",
            code_postal="63300",
        )
        assert mock_generic.called
        call_kwargs = mock_generic.call_args[1]
        filter_by = call_kwargs["filter_by"]
        assert 'codePostal = "63300"' in filter_by
        assert 'ville = "Thiers"' in filter_by


@pytest.mark.asyncio
async def test_ffbb_match_lookup_service():
    mock_candidates = [
        {
            "id": "match_thiers_gerzat_u18",
            "nom_equipe1": "SA THIERS VAILLANTE - 2",
            "nom_equipe2": "GERZAT BASKET",
            "date": "2026-10-11",
            "horaire": "11:00",
            "numero_journee": 3,
            "competition": {"nom": "DMU18 - Poule Basse 5"},
            "salle": {
                "libelle": "Maison des Sports de Thiers",
                "adresse": "Avenue Francisque Sauzedde",
                "commune": {"libelle": "Thiers", "codePostal": "63300"},
            },
        },
        {
            "id": "match_u11",
            "nom_equipe1": "SA THIERS VAILLANTE",
            "nom_equipe2": "GERZAT BASKET",
            "date": "2026-10-03",
            "horaire": "14:00",
            "competition": {"nom": "DMU11"},
        },
    ]

    with patch(
        "ffbb_mcp.services.search.search_rencontres_service",
        AsyncMock(return_value=mock_candidates),
    ):
        # 1. Lookup avec catégorie U18M2
        res = await ffbb_match_lookup_service(
            club_a="Thiers",
            club_b="Gerzat",
            categorie="U18M2",
        )
        assert res["status"] == "ok"
        assert len(res["matchs"]) == 1
        m = res["matchs"][0]
        assert m["id"] == "match_thiers_gerzat_u18"
        assert m["salle"]["nom"] == "Maison des Sports de Thiers"
        assert m["salle"]["code_postal"] == "63300"
        assert "2026-10-11" in res["presentation"]["short_answer"]
        assert "Avenue Francisque Sauzedde" in res["presentation"]["detail_line"]
        assert len(res["presentation"]["warnings"]) > 0

        # 2. Lookup introuvable
        not_found = await ffbb_match_lookup_service(
            club_a="Thiers",
            club_b="Gerzat",
            categorie="U15F",
        )
        assert not_found["status"] == "not_found"
