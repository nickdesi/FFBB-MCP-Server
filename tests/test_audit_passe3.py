"""Tests de non-régression pour l'audit FFBB MCP 3e passe (25/09/2026).

1. 🔴 filter_by dans ffbb_search : réécriture des alias de champs et transmission Meilisearch.
2. 🟠 sort dans ffbb_search : réécriture des champs de tri et respect de l'ordre global Meilisearch.
3. 🟠 Enums de ffbb_search : alignement du schéma Pydantic avec les 12 index Meilisearch.
4. 🟡 ffbb_get(type="engagement") : présentation soignée sans répétition d'ID et calendrier extrait.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ffbb_data_client.models.multi_search_results import MultiSearchResult
from ffbb_data_client.models.multi_search_results_class import MultiSearchResults
from mcp.shared.exceptions import McpError

from ffbb_mcp.server import ffbb_get
from ffbb_mcp.services.poule import get_engagement_service
from ffbb_mcp.services.search import (
    _rewrite_filter_for_index,
    _rewrite_sort_for_index,
    ffbb_search_service,
)


def test_rewrite_filter_for_index_organismes():
    """Vérifie la réécriture des alias fréquents pour les organismes."""
    raw = 'codePostal = "45560"'
    rewritten = _rewrite_filter_for_index(raw, "organismes")
    assert rewritten == 'commune.codePostal = "45560"'

    raw2 = 'ville = "Saint-Denis-en-Val"'
    assert (
        _rewrite_filter_for_index(raw2, "organismes")
        == 'commune.libelle = "Saint-Denis-en-Val"'
    )

    raw3 = 'departement = "45"'
    assert _rewrite_filter_for_index(raw3, "organismes") == 'commune.departement = "45"'


def test_rewrite_sort_for_index():
    """Vérifie la réécriture des clés de tri pour chaque index."""
    assert _rewrite_sort_for_index(["nom:asc"], "organismes") == ["nom:asc"]
    assert _rewrite_sort_for_index(["codePostal:asc"], "organismes") == [
        "commune.codePostal:asc"
    ]
    assert _rewrite_sort_for_index(["nom:desc"], "salles") == ["libelle:desc"]


@pytest.mark.asyncio
async def test_search_filter_by_forwarded_to_meilisearch(mock_client):
    """Vérifie que filter_by et sort sont correctement transmis à Meilisearch."""
    mock_hits = [
        {
            "id": 10017,
            "nom": "LA MONTJOIE SAINT DENIS EN VAL",
            "commune": {"codePostal": "45560", "libelle": "SAINT-DENIS-EN-VAL"},
        }
    ]
    res1 = MagicMock(spec=MultiSearchResult)
    res1.index_uid = "organismes"
    res1.hits = mock_hits
    res1.total_hits = 1
    res1.estimated_total_hits = 1
    mock_res = MagicMock(spec=MultiSearchResults)
    mock_res.results = [res1]

    mock_client.multi_search_async = AsyncMock(return_value=mock_res)
    mock_client._meilisearch.multi_search_async = mock_client.multi_search_async

    res = await ffbb_search_service(
        query="basket",
        type="organismes",
        filter_by='codePostal = "45560"',
        limit=5,
    )

    assert "items" in res
    assert len(res["items"]) == 1
    assert res["items"][0]["nom"] == "LA MONTJOIE SAINT DENIS EN VAL"

    # Vérifier les arguments passés à MultiSearchQuery
    mock_client.multi_search_async.assert_called()
    queries = mock_client.multi_search_async.call_args[0][0]
    assert len(queries) == 1
    q = queries[0]
    assert "organismes" in q.index_uid
    # Le terme générique 'basket' a été effacé pour permettre le filtre par code postal
    assert q.q == ""
    assert q.filter == ['commune.codePostal = "45560"']


@pytest.mark.asyncio
async def test_search_sort_preserves_meilisearch_order(mock_client):
    """Vérifie que le tri local Python ne vient pas réordonner le résultat quand sort est actif."""
    mock_hits = [
        {"id": 1, "nom": "ASVEL BASKET"},
        {"id": 2, "nom": "BASKET LANDES"},
        {"id": 3, "nom": "GRAVELINES GRAND FORT BCM"},
    ]
    res1 = MagicMock(spec=MultiSearchResult)
    res1.index_uid = "organismes"
    res1.hits = mock_hits
    res1.total_hits = 3
    res1.estimated_total_hits = 3
    mock_res = MagicMock(spec=MultiSearchResults)
    mock_res.results = [res1]

    mock_client.multi_search_async = AsyncMock(return_value=mock_res)
    mock_client._meilisearch.multi_search_async = mock_client.multi_search_async

    res = await ffbb_search_service(
        query="basket",
        type="organismes",
        sort=["nom:asc"],
        limit=5,
    )

    items = res["items"]
    noms = [item["nom"] for item in items]
    # L'ordre doit être strictement celui retourné par Meilisearch trié
    assert noms == ["ASVEL BASKET", "BASKET LANDES", "GRAVELINES GRAND FORT BCM"]


@pytest.mark.asyncio
async def test_search_unsupported_types_informative_error():
    """Vérifie que les types non indexés dans Meilisearch renvoient une McpError claire."""
    with pytest.raises(McpError) as exc_info:
        await ffbb_search_service(query="test", type="communes")
    assert "commune" in str(exc_info.value).lower()
    assert "filter_by" in str(exc_info.value)

    with pytest.raises(McpError) as exc_officiels:
        await ffbb_search_service(query="arbitre", type="officiels")
    assert "type='officiel'" in str(exc_officiels.value)


@pytest.mark.asyncio
async def test_search_news_supported(mock_client):
    """Vérifie que le type news est supporté et interroge l'index Meilisearch."""
    res1 = MagicMock(spec=MultiSearchResult)
    res1.index_uid = "ffbbsite_news"
    res1.hits = [{"id": "1", "titre": "Nouvelle saison FFBB"}]
    res1.total_hits = 1
    res1.estimated_total_hits = 1
    mock_res = MagicMock(spec=MultiSearchResults)
    mock_res.results = [res1]

    mock_client.multi_search_async = AsyncMock(return_value=mock_res)
    mock_client._meilisearch.multi_search_async = mock_client.multi_search_async

    res = await ffbb_search_service(query="saison", type="news", limit=3)
    assert "items" in res
    assert len(res["items"]) == 1
    assert res["items"][0]["titre"] == "Nouvelle saison FFBB"


@pytest.mark.asyncio
async def test_engagement_details_and_calendar(mock_client):
    """Vérifie que get_engagement_service récupère le calendrier et évite la répétition du libellé."""
    mock_engagement = {
        "id": "200000005343882",
        "numeroEquipe": 1,
        "idPoule": "200000003056111",
        "idOrganisme": "10017",
        "idCompetition": {
            "id": "200000002898000",
            "nom": "Régionale masculine seniors - Division 3",
            "typeCompetition": "PLAT",
            "categorie": {"code": "SEM"},
        },
    }
    mock_org = {
        "id": 10017,
        "nom": "LA MONTJOIE SAINT DENIS EN VAL",
        "code": "CVL0045000",
    }
    mock_poule = {
        "id": "200000003056111",
        "nom": "Poule A",
        "classements": [
            {
                "id_engagement": {
                    "id": "200000005343882",
                    "nom": "LA MONTJOIE SAINT DENIS EN VAL - 1",
                    "numero_equipe": 1,
                },
                "nom": "LA MONTJOIE SAINT DENIS EN VAL - 1",
                "match_joues": 1,
            }
        ],
        "rencontres": [
            {
                "id": "match_1",
                "date_rencontre": "2026-10-04 15:30:00",
                "joue": 1,
                "scoreEquipe1": 75,
                "scoreEquipe2": 68,
                "idEngagementEquipe1": {"id": "200000005343882"},
                "idEngagementEquipe2": {"id": "200000005343999"},
                "nomEquipe1": "LA MONTJOIE SAINT DENIS EN VAL - 1",
                "nomEquipe2": "ADVERSAIRE 1",
            },
            {
                "id": "match_2",
                "date_rencontre": "2026-10-11 15:30:00",
                "joue": 0,
                "idEngagementEquipe1": {"id": "200000005343999"},
                "idEngagementEquipe2": {"id": "200000005343882"},
                "nomEquipe1": "ADVERSAIRE 2",
                "nomEquipe2": "LA MONTJOIE SAINT DENIS EN VAL - 1",
            },
        ],
    }

    mock_client.get_engagement_async = AsyncMock(return_value=mock_engagement)
    mock_client.get_organisme_async = AsyncMock(return_value=mock_org)
    mock_client.get_poule_async = AsyncMock(return_value=mock_poule)

    data = await get_engagement_service(
        engagement_id="200000005343882", force_refresh=True
    )

    assert data["total_matchs"] == 2
    assert len(data["calendrier"]) == 2
    assert data["calendrier"][0]["id"] == "match_1"

    # Vérifier l'appel via ffbb_get pour la présentation enrichie
    with patch(
        "ffbb_mcp.server.get_engagement_service",
        new_callable=AsyncMock,
        return_value=data,
    ):
        res = await ffbb_get(id="200000005343882", type="engagement")
        presentation = res.get("presentation", {})
        short_ans = presentation.get("short_answer", "")
        detail = presentation.get("detail_line", "")
        combined = f"{short_ans}\n{detail}"

        # Vérifier qu'il n'y a pas "Engagement 200000005343882 : Engagement 200000005343882."
        assert (
            "Engagement 200000005343882 : Engagement 200000005343882." not in combined
        )
        assert "LA MONTJOIE SAINT DENIS EN VAL" in combined
        assert "2 match(s) au calendrier" in combined
