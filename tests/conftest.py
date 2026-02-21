"""Fixtures partagées pour les tests du serveur MCP FFBB."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_client():
    """Client FFBB mocké pour les tests unitaires."""
    client = MagicMock()
    # Configurer les méthodes async comme des AsyncMock
    client.get_lives_async = AsyncMock(return_value=[])
    client.get_saisons_async = AsyncMock(return_value=[])
    client.get_competition_async = AsyncMock(return_value=None)
    client.get_poule_async = AsyncMock(return_value=None)
    client.get_organisme_async = AsyncMock(return_value=None)
    client.search_competitions_async = AsyncMock(return_value=None)
    client.search_organismes_async = AsyncMock(return_value=None)
    client.search_rencontres_async = AsyncMock(return_value=None)
    client.search_salles_async = AsyncMock(return_value=None)
    client.search_pratiques_async = AsyncMock(return_value=None)
    client.search_terrains_async = AsyncMock(return_value=None)
    client.search_tournois_async = AsyncMock(return_value=None)
    client.multi_search_async = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_ctx(mock_client):
    """Contexte MCP mocké pour les tests unitaires."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.error = AsyncMock()

    # Simuler l'app_context avec le client
    app_context = MagicMock()
    app_context.client = mock_client
    ctx.app_context = app_context

    return ctx
