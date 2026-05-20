"""Tests unitaires pour le cycle de vie du client et token refresh (client.py)."""

import time
from unittest.mock import MagicMock, patch

import pytest

from ffbb_mcp.client import FFBBClientFactory, get_client_async


class DummyTokens:
    def __init__(self):
        self.api_token = "dummy_api_token"
        self.meilisearch_token = "dummy_meilisearch_token"


@pytest.mark.asyncio
async def test_client_factory_singleton_and_reset():
    """Vérifie que la factory retourne le même singleton et se réinitialise correctement."""
    FFBBClientFactory.reset()
    assert FFBBClientFactory._instance is None

    mock_client_instance = MagicMock()

    with (
        patch("ffbb_mcp.client.TokenManager.get_tokens") as mock_get_tokens,
        patch(
            "ffbb_mcp.client.FFBBDataClient.create", return_value=mock_client_instance
        ) as mock_create,
    ):
        mock_get_tokens.return_value = DummyTokens()

        # Premier appel
        client1 = await get_client_async()
        assert client1 is mock_client_instance
        assert mock_create.call_count == 1

        # Deuxième appel (doit réutiliser le singleton)
        client2 = await get_client_async()
        assert client2 is mock_client_instance
        assert mock_create.call_count == 1

        # Reset et nouvel appel (doit recréer le singleton)
        FFBBClientFactory.reset()
        assert FFBBClientFactory._instance is None

        client3 = await get_client_async()
        assert client3 is mock_client_instance
        assert mock_create.call_count == 2


@pytest.mark.asyncio
async def test_token_expiration_triggers_refresh():
    """Vérifie que l'expiration du token déclenche un rafraîchissement proactif."""
    FFBBClientFactory.reset()
    mock_client_instance = MagicMock()

    with (
        patch("ffbb_mcp.client.TokenManager.get_tokens") as mock_get_tokens,
        patch(
            "ffbb_mcp.client.FFBBDataClient.create", return_value=mock_client_instance
        ) as mock_create,
    ):
        mock_get_tokens.return_value = DummyTokens()

        # Premier appel - création initiale
        await get_client_async()
        assert mock_create.call_count == 1

        # Simuler une expiration (âge du token > 25 minutes)
        FFBBClientFactory._token_created_at = time.monotonic() - (26 * 60)

        # Deuxième appel - doit recréer le client car le token est considéré expiré
        await get_client_async()
        assert mock_create.call_count == 2


@pytest.mark.asyncio
async def test_token_refresh_failure_logging():
    """Vérifie le comportement et la capture d'exception si TokenManager lève une erreur."""
    FFBBClientFactory.reset()

    with (
        patch(
            "ffbb_mcp.client.TokenManager.get_tokens",
            side_effect=ValueError("Token generation failed"),
        ),
        patch("ffbb_mcp.client.logger.error") as mock_logger_error,
    ):
        with pytest.raises(ValueError, match="Token generation failed"):
            await get_client_async()

        # L'erreur d'initialisation doit être tracée dans les logs du serveur
        assert mock_logger_error.call_count >= 1
        log_msgs = [call.args[0] for call in mock_logger_error.call_args_list]
        assert any("initialisation asynchrone" in msg for msg in log_msgs)
