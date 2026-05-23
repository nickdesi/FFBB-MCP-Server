from unittest.mock import AsyncMock, MagicMock, patch

from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from ffbb_mcp.app_factory import create_app


def test_lifespan_calls_client_factory_reset():
    """Vérifie que la réinitialisation du client FFBBClientFactory.reset est bien appelée à l'extinction (shutdown)."""
    mcp = MagicMock()
    run_context = MagicMock()
    run_context.__aenter__ = AsyncMock(return_value=None)
    run_context.__aexit__ = AsyncMock(return_value=None)
    mcp.session_manager.run.return_value = run_context
    mcp.streamable_http_app.return_value = PlainTextResponse("ok")

    app = create_app(mcp, allowed_origins=["https://example.com"])

    with patch("ffbb_mcp.client.FFBBClientFactory.reset") as mock_reset:
        with TestClient(app) as client:
            response = client.get("/")
            assert response.status_code == 200

        # Après la fermeture du bloc TestClient (shutdown), reset() doit avoir été appelé
        mock_reset.assert_called_once()
