"""Tests de validation pour les priorités P1 et P2 de l'audit fonctionnel FFBB MCP.

Valide :
- P1 : Traçabilité réglementaire (nature, hash SHA-256, disclaimers, couverture sélective).
- P1 : Bloc de provenance (served_at, cache_hit) et consulted_scope sur réponses négatives.
- P2 : Mode compact de recherche pour agents IA (élagage des tokens).
- P2 : Traçabilité de build et métadonnées runtime (ffbb_version).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.presentation import build_provenance_block
from ffbb_mcp.services.regulations import (
    get_regulation_article_service,
    list_regulations_service,
)
from ffbb_mcp.services.search import (
    _lighten_organisme_hit,
    ffbb_search_service,
)
from ffbb_mcp.tools.system import ffbb_version

# =============================================================================
# P1 : TRAÇABILITÉ RÉGLEMENTAIRE
# =============================================================================


@pytest.mark.asyncio
async def test_get_regulation_article_traceability_contract():
    """Vérifie la présence et le format des métadonnées de traçabilité d'un article."""
    res = await get_regulation_article_service(
        document_id="rsg_ffbb_2026_2027",
        article_number="Article 28",
    )
    assert res["found"] is True
    art = res["article"]

    # 1. Nature du contenu normalisée
    assert art["content_nature"] in ("verbatim", "extrait", "synthese")

    # 2. Empreinte canonique SHA-256
    assert "content_hash" in art
    assert str(art["content_hash"]).startswith("sha256:")
    assert len(str(art["content_hash"]).split("sha256:")[1]) == 64

    # 3. Couverture du corpus
    assert art.get("corpus_coverage") == "selective_key_articles"

    # 4. Avertissement officiel
    assert "disclaimer" in art
    assert "bulletin officiel FFBB font seuls foi" in art["disclaimer"]


@pytest.mark.asyncio
async def test_list_regulations_coverage_clarity():
    """Vérifie que la liste des règlements documente clairement l'indexation sélective."""
    res = await list_regulations_service(season="2026-2027")
    assert res["coverage"] == "selective_index"
    assert "coverage_note" in res
    assert "indexed_articles" in res["coverage_note"]

    assert len(res["documents"]) > 0
    doc0 = res["documents"][0]
    assert "indexed_articles" in doc0
    assert doc0["coverage"] == "selective_key_articles"
    assert "coverage_note" in doc0


# =============================================================================
# P1 : PROVENANCE ET PÉRIMÈTRE CONSULTÉ
# =============================================================================


def test_provenance_block_served_at_and_cache_hit():
    """Vérifie la présence de served_at et cache_hit dans le bloc provenance."""
    prov_hit = build_provenance_block(cache_status="hit")
    assert prov_hit["cache_hit"] is True
    assert "served_at" in prov_hit
    assert "retrieved_at" in prov_hit

    prov_miss = build_provenance_block(cache_status="miss")
    assert prov_miss["cache_hit"] is False
    assert "served_at" in prov_miss


@pytest.mark.asyncio
async def test_negative_responses_consulted_scope():
    """Vérifie que les réponses négatives précisent consulted_scope sans masquer le périmètre."""
    from ffbb_mcp.services.club import ffbb_last_result_service, ffbb_next_match_service

    # Mock un club résolu mais sans match
    with (
        patch(
            "ffbb_mcp.services.club._resolve_team_equipes",
            AsyncMock(
                return_value=(
                    None,
                    [
                        {
                            "poule_id": "99999",
                            "engagement_id": "88888",
                            "team_label": "U13M2",
                            "nom_equipe": "Stade Clermontois",
                            "numero_equipe": 2,
                        }
                    ],
                    {"id": 9326, "nom": "Stade Clermontois"},
                )
            ),
        ),
        patch(
            "ffbb_mcp.services.club._fetch_poule_matches",
            AsyncMock(return_value=[]),
        ),
    ):
        res_next = await ffbb_next_match_service(
            organisme_id=9326, engagement_id="88888", season_id="1037"
        )
        assert res_next["status"] == "no_upcoming_match"
        assert "consulted_scope" in res_next
        assert res_next["consulted_scope"]["season_id"] == "1037"
        assert "99999" in res_next["consulted_scope"]["poules_consulted"]
        assert "périmètre consulté" in res_next["message"]

        res_last = await ffbb_last_result_service(
            organisme_id=9326, engagement_id="88888", season_id="1037"
        )
        assert res_last["status"] == "no_result"
        assert "consulted_scope" in res_last
        assert res_last["consulted_scope"]["season_id"] == "1037"
        assert "88888" in res_last["consulted_scope"]["engagements_consulted"]
        assert "périmètre consulté" in res_last["message"]


# =============================================================================
# P2 : COMPACITÉ DE LA RECHERCHE ET ALLÈGEMENT TOKENS
# =============================================================================


def test_lighten_organisme_hit_compact_mode():
    """Le mode compact doit élaguer les structures géantes et conserver les identifiants clés."""
    raw_org = {
        "id": 9326,
        "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
        "code": "ARA0063074",
        "type": "CLUB",
        "ville": "Clermont-Ferrand",
        "code_postal": "63000",
        "departement": "63",
        "cartographie": [{"lat": 45.77, "lng": 3.08}],
        "geo": {"type": "Point", "coordinates": [3.08, 45.77]},
        "facebook": None,
        "twitter": None,
        "organismeParent": {
            "id": 100,
            "nom": "COMITE DU PUY DE DOME",
            "parent": {"id": 10, "nom": "LIGUE AURA"},
        },
    }

    compact = _lighten_organisme_hit(raw_org, compact=True)
    assert compact["id"] == 9326
    assert compact["nom"] == "STADE CLERMONTOIS BASKET AUVERGNE"
    assert compact["code"] == "ARA0063074"
    assert compact["commune"] == "Clermont-Ferrand"
    assert compact["code_postal"] == "63000"
    assert compact["departement"] == "63"
    assert compact["organisme_parent"] == "COMITE DU PUY DE DOME"
    assert "cartographie" not in compact
    assert "geo" not in compact
    assert "facebook" not in compact

    standard = _lighten_organisme_hit(raw_org, compact=False)
    assert "cartographie" not in standard
    assert "facebook" not in standard
    assert standard["organismeParent"]["nom"] == "COMITE DU PUY DE DOME"


@pytest.mark.asyncio
async def test_ffbb_search_service_compact_param():
    """ffbb_search_service doit propager compact=True."""
    raw_items = [
        {
            "id": 1234,
            "nom": "AS MONTFERRAND",
            "code": "ARA0063001",
            "commune": {"libelle": "Clermont-Ferrand", "codePostal": "63100"},
            "cartographie": [1, 2, 3],
        }
    ]
    with patch(
        "ffbb_mcp.services.search._search_generic",
        AsyncMock(return_value=raw_items),
    ):
        res = await ffbb_search_service(
            query="Montferrand",
            type="organismes",
            compact=True,
        )
        assert isinstance(res, dict)
        items = res["items"]
        assert len(items) == 1
        item0 = items[0]
        assert item0["id"] == 1234
        assert item0["commune"] == "Clermont-Ferrand"
        assert item0["code_postal"] == "63100"
        assert "cartographie" not in item0


# =============================================================================
# P2 : IDENTIFICATION DU DÉPLOIEMENT (VERSION)
# =============================================================================


@pytest.mark.asyncio
async def test_ffbb_version_build_identification():
    """ffbb_version doit inclure response_schema_version et build_date en plus des sha."""
    ver = await ffbb_version()
    assert "package_version" in ver
    assert "build_sha" in ver
    assert "git_sha" in ver
    assert "build_date" in ver
    assert ver.get("response_schema_version") == "1.2.0"
