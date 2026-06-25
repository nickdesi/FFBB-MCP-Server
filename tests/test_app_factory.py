from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from ffbb_mcp.app_factory import create_app


@pytest.fixture
def app():
    mcp = MagicMock()
    mcp.session_manager.run.return_value.__aenter__ = AsyncMock(return_value=None)
    mcp.session_manager.run.return_value.__aexit__ = AsyncMock(return_value=None)
    mcp.streamable_http_app.return_value = PlainTextResponse("ok")
    return create_app(mcp, allowed_origins=["https://example.com"])


def test_request_id_header_is_preserved(app):
    client = TestClient(app)

    response = client.get("/", headers={"X-Request-ID": "req-123"})

    assert response.headers["X-Request-ID"] == "req-123"


def test_invalid_request_id_is_replaced(app):
    client = TestClient(app)

    response = client.get("/", headers={"X-Request-ID": "bad id with spaces"})

    assert response.headers["X-Request-ID"] != "bad id with spaces"
    assert response.headers["X-Request-ID"]


def test_cors_allows_configured_origin(app):
    client = TestClient(app)

    response = client.options(
        "/",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.com"


def test_lifespan_runs_mcp_session_manager():
    mcp = MagicMock()
    run_context = MagicMock()
    run_context.__aenter__ = AsyncMock(return_value=None)
    run_context.__aexit__ = AsyncMock(return_value=None)
    mcp.session_manager.run.return_value = run_context
    mcp.streamable_http_app.return_value = PlainTextResponse("ok")

    with TestClient(create_app(mcp, allowed_origins=["https://example.com"])) as client:
        response = client.get("/")

    assert response.status_code == 200
    mcp.session_manager.run.assert_called_once()
    run_context.__aenter__.assert_awaited_once()
    run_context.__aexit__.assert_awaited_once()


def test_request_id_middleware_logs_client_disconnect(caplog):
    async def failing_app(scope, receive, send):
        raise RuntimeError("broken pipe")

    mcp = MagicMock()
    mcp.session_manager.run.return_value.__aenter__ = AsyncMock(return_value=None)
    mcp.session_manager.run.return_value.__aexit__ = AsyncMock(return_value=None)
    mcp.streamable_http_app.return_value = failing_app
    client = TestClient(create_app(mcp, allowed_origins=["https://example.com"]))

    caplog.set_level("DEBUG", logger="ffbb-mcp")
    response = client.get("/", headers={"X-Request-ID": "req-disconnect"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-disconnect"
    assert "Client disconnected: broken pipe" in caplog.text


def test_request_id_middleware_returns_json_error():
    async def failing_app(scope, receive, send):
        raise RuntimeError("boom")

    mcp = MagicMock()
    mcp.session_manager.run.return_value.__aenter__ = AsyncMock(return_value=None)
    mcp.session_manager.run.return_value.__aexit__ = AsyncMock(return_value=None)
    mcp.streamable_http_app.return_value = failing_app
    client = TestClient(create_app(mcp, allowed_origins=["https://example.com"]))

    response = client.get("/", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    assert response.json() == {
        "error": "Internal Server Error",
        "request_id": "req-500",
    }
    assert response.headers["X-Request-ID"] == "req-500"


def test_request_id_middleware_logs_no_response_returned_as_disconnect(caplog):
    async def failing_app(scope, receive, send):
        raise RuntimeError("No response returned.")

    mcp = MagicMock()
    mcp.session_manager.run.return_value.__aenter__ = AsyncMock(return_value=None)
    mcp.session_manager.run.return_value.__aexit__ = AsyncMock(return_value=None)
    mcp.streamable_http_app.return_value = failing_app
    client = TestClient(create_app(mcp, allowed_origins=["https://example.com"]))

    caplog.set_level("DEBUG", logger="ffbb-mcp")
    response = client.get("/", headers={"X-Request-ID": "req-disconnect-no-resp"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-disconnect-no-resp"
    assert "Client disconnected: No response returned." in caplog.text


def test_sse_response_adds_buffering_headers():
    from starlette.responses import StreamingResponse

    async def sse_app(scope, receive, send):
        response = StreamingResponse(
            iter(["data: hello\n\n"]), media_type="text/event-stream"
        )
        await response(scope, receive, send)

    mcp = MagicMock()
    mcp.session_manager.run.return_value.__aenter__ = AsyncMock(return_value=None)
    mcp.session_manager.run.return_value.__aexit__ = AsyncMock(return_value=None)
    mcp.streamable_http_app.return_value = sse_app
    client = TestClient(create_app(mcp, allowed_origins=["https://example.com"]))

    response = client.get("/")

    assert response.headers["X-Accel-Buffering"] == "no"
    assert "no-cache" in response.headers["Cache-Control"]
