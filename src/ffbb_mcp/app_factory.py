from __future__ import annotations

import contextlib
import logging
import os
import re
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from mcp.server.fastmcp import FastMCP

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

logger = logging.getLogger("ffbb-mcp")

_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


def create_app(mcp: FastMCP, allowed_origins: list[str]) -> Starlette:
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None]:
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                try:
                    from ffbb_mcp.client import FFBBClientFactory

                    FFBBClientFactory.reset()
                except Exception as e:
                    logger.warning(
                        "Erreur lors de la réinitialisation du client au shutdown : %s",
                        e,
                    )

    mcp_app = mcp.streamable_http_app()

    app = Starlette(
        debug=False,
        routes=[Mount("/", app=mcp_app)],
        lifespan=lifespan,
    )
    app.router.redirect_slashes = False

    # Default to trusting only localhost; set TRUSTED_PROXY_HOSTS for production
    # reverse-proxy scenarios (e.g. "10.0.0.1,10.0.0.2").
    _proxy_hosts_raw = os.environ.get("TRUSTED_PROXY_HOSTS", "127.0.0.1")
    _trusted_hosts = [h.strip() for h in _proxy_hosts_raw.split(",") if h.strip()]
    app.add_middleware(
        ProxyHeadersMiddleware, trusted_hosts=_trusted_hosts or ["127.0.0.1"]
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
        allow_headers=[
            "Content-Type",
            "Accept",
            "Authorization",
            "Mcp-Session-Id",
            "MCP-Protocol-Version",
            "X-Forwarded-For",
            "X-Forwarded-Proto",
            "X-Real-IP",
        ],
        expose_headers=["Content-Type", "Mcp-Session-Id"],
    )

    app.add_middleware(GZipMiddleware, minimum_size=1000)

    class RequestIdMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            raw_id = request.headers.get("X-Request-ID", "")
            request_id = raw_id if _REQUEST_ID_RE.match(raw_id) else str(uuid.uuid4())
            try:
                response = await call_next(request)
            except Exception as e:
                # Don't log broken pipes or client disconnects as errors
                err_str = str(e).lower()
                if any(
                    x in err_str
                    for x in ["broken pipe", "connection closed", "client disconnected"]
                ):
                    logger.debug("Client disconnected: %s", e)
                else:
                    logger.error(
                        "Middleware error on %s: %s", request.url.path, e, exc_info=True
                    )

                response = JSONResponse(
                    {"error": "Internal Server Error", "request_id": request_id},
                    status_code=500,
                )

            response.headers["X-Request-ID"] = request_id
            return response

    app.add_middleware(RequestIdMiddleware)

    return app
