from __future__ import annotations

import contextlib
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

import anyio
from sse_starlette import EventSourceResponse

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.types import Send

logger = logging.getLogger("ffbb-mcp")

_PATCHED = False


def apply_sse_reconnect_patch() -> None:
    """Patch StreamableHTTPServerTransport to gracefully handle SSE stream reconnections.

    By default in MCP Python SDK, if an MCP client (such as Google Antigravity) reconnects
    its standalone GET SSE stream on an existing session, the server rejects it with:
    'HTTP 409 Conflict: Only one SSE stream is allowed per session'.

    The MCP SDK documentation explicitly notes:
    'Currently, client reconnection for standalone GET streams is NOT implemented - this is a known gap'.

    This patch bridges that gap: when a client requests a new GET stream for an existing session,
    the previous stale stream is cleanly closed and replaced without error, allowing seamless
    session continuity.
    """
    global _PATCHED
    if _PATCHED:
        return

    try:
        from mcp.server.streamable_http import (
            CONTENT_TYPE_SSE,
            GET_STREAM_KEY,
            LAST_EVENT_ID_HEADER,
            MCP_SESSION_ID_HEADER,
            REQUEST_STREAM_BUFFER_SIZE,
            EventMessage,
            SSEEvent,
            StreamableHTTPServerTransport,
        )
    except ImportError:  # pragma: no cover - robustness
        logger.warning(
            "mcp.server.streamable_http non disponible, patch de reconnexion SSE ignoré."
        )
        return

    async def _graceful_handle_get_request(
        self: StreamableHTTPServerTransport, request: Request, send: Send
    ) -> None:
        writer = self._read_stream_writer
        if writer is None:
            raise ValueError(
                "No read stream writer available. Ensure connect() is called first."
            )

        # Validate Accept header - must include text/event-stream
        _, has_sse = self._check_accept_headers(request)

        if not has_sse:
            response = self._create_error_response(
                "Not Acceptable: Client must accept text/event-stream",
                HTTPStatus.NOT_ACCEPTABLE,
            )
            await response(request.scope, request.receive, send)
            return

        if not await self._validate_request_headers(request, send):
            return

        # Handle resumability: check for Last-Event-ID header
        if last_event_id := request.headers.get(LAST_EVENT_ID_HEADER):
            await self._replay_events(last_event_id, request, send)
            return

        headers = {
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "Content-Type": CONTENT_TYPE_SSE,
        }

        if self.mcp_session_id:
            headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        # Reconnexion gracieuse : au lieu de renvoyer une erreur 409 Conflict,
        # on ferme proprement l'ancien flux déconnecté/orphelin pour accepter le nouveau.
        if GET_STREAM_KEY in self._request_streams:
            logger.info(
                "Session %s : Reconnexion du flux SSE demandée. Remplacement du flux précédent.",
                self.mcp_session_id,
            )
            old_streams = self._request_streams.pop(GET_STREAM_KEY, None)
            if old_streams:
                with contextlib.suppress(Exception):
                    await old_streams[0].aclose()
                with contextlib.suppress(Exception):
                    await old_streams[1].aclose()

        # Create SSE stream
        sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream[
            SSEEvent
        ](0)
        stream_pair = anyio.create_memory_object_stream[EventMessage](
            REQUEST_STREAM_BUFFER_SIZE
        )

        async def standalone_sse_writer() -> None:
            try:
                self._request_streams[GET_STREAM_KEY] = stream_pair
                standalone_stream_reader = stream_pair[1]

                async with sse_stream_writer, standalone_stream_reader:
                    async for event_message in standalone_stream_reader:
                        event_data = self._create_event_data(event_message)
                        await sse_stream_writer.send(event_data)
            except Exception:
                logger.exception("Error in standalone SSE writer")
            finally:
                logger.debug("Closing standalone SSE writer")
                if self._request_streams.get(GET_STREAM_KEY) == stream_pair:
                    await self._clean_up_memory_streams(GET_STREAM_KEY)

        # Create and start EventSourceResponse
        response = EventSourceResponse(
            content=sse_stream_reader,
            data_sender_callable=standalone_sse_writer,
            headers=headers,
        )

        try:
            # This will send headers immediately and establish the SSE connection
            await response(request.scope, request.receive, send)
        except Exception:
            logger.exception("Error in standalone SSE response")
            await sse_stream_writer.aclose()
            await sse_stream_reader.aclose()
            if self._request_streams.get(GET_STREAM_KEY) == stream_pair:
                await self._clean_up_memory_streams(GET_STREAM_KEY)

    StreamableHTTPServerTransport._handle_get_request = (  # type: ignore[method-assign]
        _graceful_handle_get_request
    )
    _PATCHED = True
    logger.info(
        "✅ Patch de reconnexion gracieuse StreamableHTTP SSE appliqué avec succès."
    )
