import contextlib
import logging
from collections.abc import AsyncGenerator
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import Mount
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

logger = logging.getLogger("ffbb-mcp")


def create_app(mcp: FastMCP, allowed_origins: list[str]) -> Starlette:
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with mcp.session_manager.run():
            yield

    mcp_app = mcp.streamable_http_app()

    app = Starlette(
        debug=False,
        routes=[Mount("/", app=mcp_app)],
        lifespan=lifespan,
    )
    app.router.redirect_slashes = False

    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

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

    import uuid

    from starlette.middleware.base import BaseHTTPMiddleware

    class RequestIdMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

    app.add_middleware(RequestIdMiddleware)

    return app
