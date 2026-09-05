import anyio
import httpx
import pytest
from httpx import ASGITransport
from mcp.server.streamable_http import GET_STREAM_KEY

from ffbb_mcp.app_factory import create_app
from ffbb_mcp.server import mcp


@pytest.mark.asyncio
async def test_sse_stream_reconnection_replaces_old_stream_without_conflict():
    """Vérifie que la reconnexion d'un flux SSE sur la même session n'entraîne pas d'erreur 409 Conflict.

    Comble la lacune connue du SDK MCP StreamableHTTP où la reconnexion d'un flux GET standalone
    déclenchait un 409 Conflict bloquant Antigravity et les clients SSE.
    """
    app = create_app(mcp, allowed_origins=["*"])
    async with mcp.session_manager.run():
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            # 1. Initialisation de la session
            init_resp = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0"},
                    },
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            assert init_resp.status_code == 200
            session_id = init_resp.headers.get("mcp-session-id")
            assert session_id is not None

            # 2. Simuler un premier flux GET actif dans le transport
            server_instance = mcp.session_manager._server_instances.get(session_id)
            assert server_instance is not None
            server_instance._request_streams[GET_STREAM_KEY] = (
                anyio.create_memory_object_stream(10)
            )
            assert GET_STREAM_KEY in server_instance._request_streams

            # 3. Établir une reconnexion GET SSE sur cette même session
            headers_captured: dict[str, str] = {}
            status_captured: list[int] = []

            async def mock_send(message: dict):
                if message["type"] == "http.response.start":
                    status_captured.append(message["status"])
                    for k, v in message.get("headers", []):
                        headers_captured[k.decode("latin1")] = v.decode("latin1")

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/mcp",
                "headers": [
                    (b"accept", b"text/event-stream"),
                    (b"mcp-session-id", session_id.encode("utf-8")),
                ],
                "query_string": b"",
            }

            async def mock_receive():
                await anyio.sleep(10)
                return {"type": "http.disconnect"}

            # Exécuter handle_request avec un timeout bref pour ne pas bloquer sur l'attente SSE
            with anyio.move_on_after(0.2):
                await server_instance.handle_request(scope, mock_receive, mock_send)

            # 4. Vérifier que la réponse est 200 OK text/event-stream et JAMAIS 409 Conflict
            assert status_captured == [200], (
                f"Attendu HTTP 200 mais reçu {status_captured}"
            )
            assert headers_captured.get("content-type") == "text/event-stream"
            assert headers_captured.get("mcp-session-id") == session_id

            # 5. Vérifier que les appels d'outils continuent de fonctionner parfaitement sur cette session
            tool_resp = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "ffbb_version", "arguments": {}},
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "mcp-session-id": session_id,
                },
            )
            assert tool_resp.status_code == 200
            result = tool_resp.json().get("result", {})
            assert "structuredContent" in result or "content" in result
