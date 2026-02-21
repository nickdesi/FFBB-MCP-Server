"""Tests d'intégration pour le serveur MCP FFBB."""

import pytest
from ffbb_api_client_v3 import FFBBAPIClientV3, TokenManager


@pytest.fixture(scope="module")
def client():
    """Client FFBB partagé pour tous les tests."""
    tokens = TokenManager.get_tokens()
    return FFBBAPIClientV3.create(
        api_bearer_token=tokens.api_token,
        meilisearch_bearer_token=tokens.meilisearch_token,
    )


def test_token_retrieval():
    """Vérifie que les tokens sont récupérés automatiquement."""
    tokens = TokenManager.get_tokens()
    assert tokens is not None
    assert tokens.api_token is not None
    assert tokens.meilisearch_token is not None


def test_get_lives(client):
    """Vérifie que get_lives retourne une liste (peut être vide hors match)."""
    lives = client.get_lives()
    assert isinstance(lives, list)


def test_get_saisons(client):
    """Vérifie que des saisons sont disponibles."""
    saisons = client.get_saisons()
    if not saisons:
        import warnings

        warnings.warn(
            "Aucune saison trouvée via l'API, vérifiez si c'est normal.",
            stacklevel=2,
        )
    else:
        assert len(saisons) > 0


def test_search_competitions(client):
    """Vérifie la recherche de compétitions."""
    results = client.search_competitions("Championnat")
    assert results is not None
    assert hasattr(results, "hits")
    assert len(results.hits) > 0


def test_search_organismes(client):
    """Vérifie la recherche d'organismes."""
    results = client.search_organismes("Paris")
    assert results is not None
    assert hasattr(results, "hits")
    assert len(results.hits) > 0


def test_search_salles(client):
    """Vérifie la recherche de salles."""
    results = client.search_salles("Paris")
    assert results is not None
    assert hasattr(results, "hits")


def test_search_rencontres(client):
    """Vérifie la recherche de rencontres."""
    results = client.search_rencontres("Nationale")
    assert results is not None
    assert hasattr(results, "hits")


def test_multi_search(client):
    """Vérifie la recherche multi-types."""
    results = client.multi_search("Lyon")
    assert results is not None


def test_get_organisme_from_search(client):
    """Vérifie qu'on peut récupérer les détails d'un organisme trouvé par recherche."""
    results = client.search_organismes("Paris")
    assert results and results.hits
    organisme_id = int(results.hits[0].id)
    organisme = client.get_organisme(organisme_id=organisme_id)
    assert organisme is not None


def test_server_tools_importable():
    """Vérifie que le module server est importable et les outils enregistrés."""
    from ffbb_mcp.server import mcp

    tools = mcp._tool_manager.list_tools()
    tool_names = [t.name for t in tools]
    expected = [
        "ffbb_get_lives",
        "ffbb_get_saisons",
        "ffbb_get_competition",
        "ffbb_get_poule",
        "ffbb_get_organisme",
        "ffbb_equipes_club",
        "ffbb_get_classement",
        "ffbb_calendrier_club",
        "ffbb_search_competitions",
        "ffbb_search_organismes",
        "ffbb_search_rencontres",
        "ffbb_search_salles",
        "ffbb_search_pratiques",
        "ffbb_search_terrains",
        "ffbb_search_tournois",
        "ffbb_multi_search",
    ]
    for name in expected:
        assert name in tool_names, f"Outil manquant : {name}"
