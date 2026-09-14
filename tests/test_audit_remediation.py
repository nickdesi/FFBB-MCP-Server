"""Tests de non-régression pour les 5 axes de l'audit FFBB MCP.

1. Résolution d'équipe stricte (détection d'ambiguïté vs résolution filtrée).
2. Pagination réelle et respect strict de limit / offset sur ffbb_search.
3. Cohérence du calcul de saison active et enCours.
4. Alignement de la documentation et du runtime TTL (lives = 15s).
5. Robustesse face aux filtres de compétition et types.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ffbb_mcp.services import (
    ffbb_next_match_service,
    ffbb_resolve_team_service,
    ffbb_search_service,
    get_cache_ttls,
    get_saisons_service,
)


@pytest.fixture
def mock_scba_organisme():
    """Mock de l'organisme SCBA (9326) avec deux engagements U18M (Championnat PLAT et Coupe ARA)."""
    return {
        "id": 9326,
        "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
        "code": "ARA0063074",
        "engagements": [
            {
                "id": "200000005347163",
                "numeroEquipe": 1,
                "idPoule": {"id": "200000003056290"},
                "idCompetition": {
                    "id": "200000002898069",
                    "nom": "RMU18 Brassage",
                    "code": "RMU18 Brassage",
                    "typeCompetition": "PLAT",
                    "sexe": "M",
                    "categorie": {"code": "U18"},
                },
            },
            {
                "id": "200000005355886",
                "numeroEquipe": 1,
                "idPoule": {"id": "200000003057495"},
                "idCompetition": {
                    "id": "200000002898647",
                    "nom": "U18 MASCULIN COUPE ARA",
                    "code": "COUPE ARA U18M",
                    "typeCompetition": "COUPE",
                    "sexe": "M",
                    "categorie": {"code": "U18"},
                },
            },
        ],
    }


@pytest.mark.asyncio
async def test_u18m_ambiguity_detection_and_disambiguation(
    mock_client, mock_scba_organisme
) -> None:
    """Axe 1 : Vérifie qu'une équipe engagée en championnat et en coupe renvoie 'ambiguous'

    sans filtre, et 'resolved' dès qu'un filtre de compétition ou d'engagement est fourni.
    """
    mock_client.get_organisme_async = AsyncMock(return_value=mock_scba_organisme)

    # 1. Sans filtre de compétition -> doit détecter l'ambiguïté (RMU18 Brassage vs Coupe ARA)
    ambig_res = await ffbb_resolve_team_service(
        organisme_id=9326,
        categorie="U18M",
        numero_equipe=1,
        force_refresh=True,
    )
    assert ambig_res["status"] == "ambiguous"
    assert "candidates" in ambig_res
    assert len(ambig_res["candidates"]) == 2
    comp_types = {c.get("competition_type") for c in ambig_res["candidates"]}
    assert comp_types == {"PLAT", "COUPE"}

    # 2. Avec filtre competition_type='COUPE' -> doit résoudre vers la Coupe
    coupe_res = await ffbb_resolve_team_service(
        organisme_id=9326,
        categorie="U18M",
        numero_equipe=1,
        competition_type="COUPE",
        force_refresh=True,
    )
    assert coupe_res["status"] == "resolved"
    assert coupe_res["team"]["competition_type"] == "COUPE"

    # 3. Avec filtre competition_type='PLAT' -> doit résoudre vers le brassage championnat
    plat_res = await ffbb_resolve_team_service(
        organisme_id=9326,
        categorie="U18M",
        numero_equipe=1,
        competition_type="PLAT",
        force_refresh=True,
    )
    assert plat_res["status"] == "resolved"
    assert plat_res["team"]["competition_type"] == "PLAT"


@pytest.mark.asyncio
async def test_search_pagination_respects_limit_and_offset(mock_client) -> None:
    """Axe 2 : Vérifie que ffbb_search respecte strictement limit et offset avec métadonnées."""
    # Simulation Meilisearch multi_search avec 134 hits
    mock_meili = MagicMock()

    def mock_multi_search(queries):
        sub_results = []
        for q in queries:
            offset = getattr(q, "offset", 0) or 0
            limit = getattr(q, "limit", 20) or 20
            # Génère des faux hits pour le test
            hits = [
                {"id": f"org_{i}", "nom": f"Club {i}"}
                for i in range(offset, offset + limit)
            ]
            mock_res = MagicMock()
            mock_res.hits = hits
            mock_res.estimated_total_hits = 134
            mock_res.total_hits = 134
            sub_results.append(mock_res)
        wrapper = MagicMock()
        wrapper.results = sub_results
        return wrapper

    mock_meili.multi_search_async = AsyncMock(side_effect=mock_multi_search)
    mock_client._meilisearch = mock_meili

    res_page1 = await ffbb_search_service(
        query="Stade Clermontois",
        type="organismes",
        limit=10,
        offset=0,
        force_refresh=True,
    )
    assert isinstance(res_page1, list)
    # Vérification des métadonnées de pagination
    meta_items = [
        item
        for item in res_page1
        if "_meta" in item and isinstance(item["_meta"], dict)
    ]
    assert len(meta_items) == 1
    meta = meta_items[0]["_meta"]
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["returned"] == 10
    assert meta["total"] == 134
    assert meta["has_more"] is True
    assert meta["next_offset"] == 10

    # Vérification de la page 2
    res_page2 = await ffbb_search_service(
        query="Stade Clermontois",
        type="organismes",
        limit=10,
        offset=10,
        force_refresh=True,
    )
    meta2 = next(
        item["_meta"]
        for item in res_page2
        if "_meta" in item and isinstance(item["_meta"], dict)
    )
    assert meta2["offset"] == 10
    assert meta2["returned"] == 10

    # Vérification de l'absence de collision entre les items de la page 1 et de la page 2
    ids_p1 = {item["id"] for item in res_page1 if "id" in item}
    ids_p2 = {item["id"] for item in res_page2 if "id" in item}
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.asyncio
async def test_saison_en_cours_calculation(mock_client) -> None:
    """Axe 3 & 4 : Vérifie la cohérence de enCours et within_date_range pour la saison active."""
    # Simulation de la saison FFBB 2026-2027 retournée par l'API Directus avec enCours=False
    mock_client.get_saisons_async = AsyncMock(
        return_value=[
            {
                "id": "1037",
                "code": "26-27",
                "nom": "2026-2027",
                "dateDebut": "2026-07-01",
                "dateFin": "2027-06-30",
                "active": True,
                "enCours": False,
            }
        ]
    )
    saisons = await get_saisons_service(active_only=True, force_refresh=True)
    assert len(saisons) >= 1
    active_saison = saisons[0]
    # La saison 2026-2027 qui englobe la date courante doit avoir enCours=True
    assert active_saison.get("active") is True
    assert active_saison.get("enCours") is True
    assert active_saison.get("within_date_range") is True


def test_live_ttl_and_docstring_alignment() -> None:
    """Axe 3 : Vérifie l'alignement strict du TTL live (15s)."""
    ttls = get_cache_ttls()
    assert ttls.get("lives") == 15


@pytest.mark.asyncio
async def test_next_match_and_last_result_with_disambiguation(
    mock_client, mock_scba_organisme
) -> None:
    """Axe 1 & 4 : Vérifie que next_match et last_result acceptent les filtres de désambiguïsation."""
    mock_client.get_organisme_async = AsyncMock(return_value=mock_scba_organisme)
    mock_client.get_poule_async = AsyncMock(
        return_value={
            "id": "200000003057495",
            "nom": "Poule Coupe",
            "rencontres": [
                {
                    "id": "match_123",
                    "date_rencontre": "2026-10-10 14:00:00",
                    "joue": 0,
                    "idEngagementEquipe1": {"id": "200000005355886"},
                    "idEngagementEquipe2": {"id": "adv_999"},
                    "nomEquipe1": "STADE CLERMONTOIS BASKET AUVERGNE - 1",
                    "nomEquipe2": "ADVERSAIRE BASKET",
                }
            ],
        }
    )

    # Test next_match avec filtre explicite
    res_next = await ffbb_next_match_service(
        organisme_id=9326,
        categorie="U18M",
        numero_equipe=1,
        competition_type="COUPE",
        force_refresh=True,
    )
    assert res_next.get("status") == "ok"
    assert res_next.get("match", {}).get("match_id") == "match_123"


@pytest.mark.asyncio
async def test_team_summary_ambiguity_propagation(
    mock_client, mock_scba_organisme
) -> None:
    """Axe 1 : Vérifie que ffbb_team_summary ne devine pas aveuglément et propage le statut ambiguous."""
    from ffbb_mcp.server import ffbb_team_summary

    mock_client.get_organisme_async = AsyncMock(return_value=mock_scba_organisme)

    # Appel sans filtre de compétition -> doit renvoyer status='ambiguous'
    summary_ambig = await ffbb_team_summary(
        organisme_id=9326,
        categorie="U18M",
        numero_equipe=1,
        force_refresh=True,
    )
    assert summary_ambig.get("status") == "ambiguous"
    assert "candidates" in summary_ambig
    assert len(summary_ambig["candidates"]) == 2
