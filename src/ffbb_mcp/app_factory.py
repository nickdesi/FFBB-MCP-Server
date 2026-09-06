from __future__ import annotations

import asyncio
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
from starlette.routing import Mount
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from ffbb_mcp._state import _read_positive_int_env
from ffbb_mcp.cache_strategy import is_in_match_window
from ffbb_mcp.utils import OrjsonResponse

logger = logging.getLogger("ffbb-mcp")

_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")

# Intervalle de rafraîchissement proactif du cache « lives » (secondes).
_LIVES_REFRESH_INTERVAL = _read_positive_int_env("FFBB_LIVES_REFRESH_INTERVAL", 10)


async def _background_lives_refresh_loop() -> None:
    """Rafraîchit proactivement les matchs en cours pendant les fenêtres de match.

    Ne tourne qu'en mode HTTP (serveur longue durée) : les données live sont
    ainsi toujours à jour en cache, l'utilisateur ne subit jamais la latence
    (~400ms) d'un miss sur le chemin le plus chaud.
    """
    while True:
        try:
            await asyncio.sleep(_LIVES_REFRESH_INTERVAL)
            if not is_in_match_window():
                continue
            from ffbb_mcp.services.poule import _fetch_lives

            await _fetch_lives()
        except asyncio.CancelledError:
            break
        except Exception:  # pragma: no cover - robustness
            logger.debug("Refresh lives en arrière-plan échoué", exc_info=True)


async def _bootstrap_cache() -> None:
    """Préchauffe les données chaudes au démarrage (saisons, lives, organismes)."""
    try:
        from ffbb_mcp.services.poule import get_lives_service, get_saisons_service

        await get_saisons_service(active_only=True)
        await get_lives_service()
    except Exception:  # pragma: no cover - robustness
        logger.debug("Bootstrap cache (saisons/lives) échoué", exc_info=True)
    try:
        from ffbb_mcp.services.warmup import warmup_cache_service

        await warmup_cache_service()
    except Exception:  # pragma: no cover - robustness
        logger.debug("Warm-up organismes échoué", exc_info=True)


def create_app(mcp: FastMCP, allowed_origins: list[str]) -> Starlette:
    from ffbb_mcp.sse_patch import (
        apply_fastmcp_json_formatting_patch,
        apply_sse_reconnect_patch,
    )

    apply_sse_reconnect_patch()
    apply_fastmcp_json_formatting_patch()

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None]:
        # Tâches de fond réservées au mode HTTP (1 client = 1 requête en stdio).
        background_tasks: list[asyncio.Task[None]] = []
        if os.environ.get("MCP_MODE", "stdio").lower() not in ("stdio", ""):
            background_tasks.append(
                asyncio.ensure_future(_background_lives_refresh_loop())
            )
            background_tasks.append(asyncio.ensure_future(_bootstrap_cache()))
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                for task in background_tasks:
                    task.cancel()
                for task in background_tasks:
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
                try:
                    from ffbb_mcp.client import FFBBClientFactory

                    await FFBBClientFactory.close_client_async()
                except Exception as e:
                    logger.warning(
                        "Erreur lors de la fermeture asynchrone du client au shutdown : %s",
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
                    for x in [
                        "broken pipe",
                        "connection closed",
                        "connection reset",
                        "connection aborted",
                        "client disconnected",
                        "no response returned",
                        "context canceled",
                        "context cancelled",
                        "endofstream",
                        "eof",
                    ]
                ):
                    logger.debug("Client disconnected: %s", e)
                else:
                    logger.error(
                        "Middleware error on %s: %s", request.url.path, e, exc_info=True
                    )

                response = OrjsonResponse(
                    {"error": "Internal Server Error", "request_id": request_id},
                    status_code=500,
                )

            response.headers["X-Request-ID"] = request_id

            # Désactiver le buffering de Nginx/OpenResty pour les flux SSE
            content_type = response.headers.get("content-type", "").lower()
            if "text/event-stream" in content_type:
                response.headers["X-Accel-Buffering"] = "no"
                response.headers["Cache-Control"] = "no-cache, no-transform"

            return response

    app.add_middleware(RequestIdMiddleware)

    return app
