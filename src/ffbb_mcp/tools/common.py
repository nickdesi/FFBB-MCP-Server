"""Utilitaires et décorateurs partagés par tous les modules de tools FastMCP."""

from __future__ import annotations

import logging
import sys
from functools import wraps
from typing import TYPE_CHECKING, Any

from mcp.types import ToolAnnotations

from ffbb_mcp.metrics import record_tool_call
from ffbb_mcp.services import handle_api_error

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context

logger = logging.getLogger("ffbb-mcp")

_READONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


def track_tool_usage(tool_name: str):
    """Décorateur léger pour compter les appels par outil MCP."""

    def decorator(func: Any) -> Any:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            record_tool_call(tool_name)
            return await func(*args, **kwargs)

        return wrapper

    return decorator


async def _safe_report_progress(
    ctx: Context | None,
    progress: float,
    total: float | None = None,
    message: str | None = None,
) -> None:
    """Rapporte la progression à FastMCP sans bloquer en l'absence de request."""
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress, total=total, message=message)
    except (ValueError, AssertionError):
        logger.debug("progress report skipped", exc_info=True)


def _get_server_service(service_name: str, default: Any) -> Any:
    """Résout dynamiquement un service depuis ffbb_mcp.server pour compatibilité mocks."""
    server_mod = sys.modules.get("ffbb_mcp.server")
    if server_mod is not None:
        return getattr(server_mod, service_name, default)
    return default


__all__ = [
    "_READONLY_ANNOTATIONS",
    "_get_server_service",
    "_safe_report_progress",
    "handle_api_error",
    "logger",
    "track_tool_usage",
]
