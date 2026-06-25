from __future__ import annotations

# Note mypy: les annotations `# type: ignore[untyped-decorator]` du fichier
# (sur `@mcp.custom_route(...)`) proviennent uniquement du décorateur
# FastMCP `mcp.custom_route` dont les stubs officiels ne sont pas typés.
# Pas de fond à corriger côté projet — la convention est documentée ici.
import asyncio
import datetime
import logging
import os
import platform
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from starlette.requests import Request

from starlette.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from . import __version__ as _PACKAGE_VERSION
from .benchmark import get_benchmark_trends, run_benchmark
from .dashboard import _build_dashboard_html
from .metrics import generate_prometheus_metrics, get_snapshot, summarize_health
from .utils import OrjsonResponse

_DEFAULT_PUBLIC_URL = "https://ffbb.desimone.fr"
_REMOTE_LOGO_URL = (
    "https://raw.githubusercontent.com/nickdesi/FFBB-MCP-Server/main/assets/logo.webp"
)
logger = logging.getLogger("ffbb-mcp")
_background_tasks: set[asyncio.Task] = set()


def _find_website_dir() -> Path:
    # Détecte le dossier website/ en local ou en production
    repo_path = Path(__file__).resolve().parents[2] / "website"
    if repo_path.exists():
        return repo_path
    pkg_path = Path(__file__).resolve().parent / "website"
    if pkg_path.exists():
        return pkg_path
    prod_path = Path("/app/website")
    if prod_path.exists():
        return prod_path
    return Path.cwd() / "website"


_WEBSITE_DIR = _find_website_dir()
_LOGO_PATH = _WEBSITE_DIR / "logo.webp"


def _get_public_base_url() -> str:
    public_url = os.environ.get("PUBLIC_URL", _DEFAULT_PUBLIC_URL).strip()
    if not public_url:
        return _DEFAULT_PUBLIC_URL
    normalized = public_url.rstrip("/")
    if normalized.endswith("/mcp"):
        normalized = normalized[: -len("/mcp")]
    return normalized or _DEFAULT_PUBLIC_URL


def _get_logo_url() -> str:
    return f"{_get_public_base_url()}/logo.webp"


def _build_index_html() -> str:
    index_path = _WEBSITE_DIR / "index.html"
    if index_path.exists():
        try:
            return index_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read index.html: {e}")
    return (
        "<html><body><h1>FFBB MCP Server</h1><p>Site en maintenance.</p></body></html>"
    )


def _build_robots_txt() -> str:
    base_url = _get_public_base_url()
    return f"User-agent: *\nAllow: /\nAllow: /docs/\nSitemap: {base_url}/sitemap.xml\n"


def _build_sitemap_xml() -> str:
    canonical_url = f"{_get_public_base_url()}/"
    lastmod = datetime.date.today().isoformat()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{canonical_url}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{canonical_url}docs/</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
"""


def _logo_response() -> Response:
    if _LOGO_PATH.exists():
        return FileResponse(_LOGO_PATH, media_type="image/webp")
    return RedirectResponse(_REMOTE_LOGO_URL)


def register_routes(mcp: FastMCP) -> None:
    """Registers all custom HTTP routes on the FastMCP instance."""

    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
    async def health(request: Request) -> Response:
        """Endpoint de santé enrichi — lisible par machine et humain."""
        snap = get_snapshot()
        summary = summarize_health(snap)
        uptime_s = snap["uptime_seconds"]
        days = int(uptime_s // 86400)
        hours = int((uptime_s % 86400) // 3600)
        minutes = int((uptime_s % 3600) // 60)
        seconds = int(uptime_s % 60)
        return OrjsonResponse(
            {
                "status": summary["status"],
                "service": "ffbb-mcp",
                "version": _PACKAGE_VERSION,
                "transport": "streamable-http",
                "spec": "2025-11-25",
                "uptime_seconds": round(uptime_s, 1),
                "uptime_human": f"{days}j {hours:02d}:{minutes:02d}:{seconds:02d}",
                "api_calls_total": summary["api_calls_total"],
                "api_calls_success": summary["api_calls_success"],
                "api_errors_total": summary["api_errors_total"],
                "api_error_rate": round(summary["api_error_rate"], 4),
                "api_avg_latency_ms": round(
                    summary["api_avg_latency_seconds"] * 1000, 2
                ),
                "api_inflight_requests": summary["api_inflight_requests"],
                "cache_hits_total": summary["cache_hits_total"],
                "cache_misses_total": summary["cache_misses_total"],
                "cache_hit_ratio_global": round(summary["cache_hit_ratio_global"], 4),
                "timestamp": datetime.datetime.now(datetime.UTC)
                .replace(tzinfo=None)
                .isoformat()
                + "Z",
                "python_version": platform.python_version(),
                "public_url": _get_public_base_url(),
            }
        )

    @mcp.custom_route("/metrics", methods=["GET"])  # type: ignore[untyped-decorator]
    async def metrics(request: Request) -> Response:
        return PlainTextResponse(generate_prometheus_metrics())

    @mcp.custom_route("/metrics.json", methods=["GET"])  # type: ignore[untyped-decorator]
    async def metrics_json(request: Request) -> Response:
        """Snapshot des métriques au format JSON (pour le dashboard front-end)."""
        snap = get_snapshot()
        if "cache_miss_reasons" in snap:
            snap["cache_miss_reasons"] = {
                f"{cache}:{reason}": count
                for (cache, reason), count in snap["cache_miss_reasons"].items()
            }
        return OrjsonResponse(
            {
                "service": "ffbb-mcp",
                "version": _PACKAGE_VERSION,
                "timestamp": datetime.datetime.now(datetime.UTC)
                .replace(tzinfo=None)
                .isoformat()
                + "Z",
                **snap,
            }
        )

    @mcp.custom_route("/dashboard", methods=["GET"])  # type: ignore[untyped-decorator]
    async def dashboard(request: Request) -> Response:
        """Dashboard de supervision HTML — lisible humain, demo-friendly."""
        return HTMLResponse(content=_build_dashboard_html(), status_code=200)

    @mcp.custom_route("/benchmark", methods=["GET"])  # type: ignore[untyped-decorator]
    async def benchmark_get(request: Request) -> Response:
        """Retourne les tendances historiques du benchmark."""
        trends = get_benchmark_trends()
        if os.environ.get("FFBB_ENABLE_BENCHMARK", "").lower() != "true":
            trends["benchmark_enabled"] = False
            trends["hint"] = "Set FFBB_ENABLE_BENCHMARK=true to run benchmarks"
        else:
            trends["benchmark_enabled"] = True
        return OrjsonResponse(trends)

    @mcp.custom_route("/benchmark/run", methods=["POST"])  # type: ignore[untyped-decorator]
    async def benchmark_post(request: Request) -> Response:
        """Exécute un benchmark de performance."""
        if os.environ.get("FFBB_ENABLE_BENCHMARK", "").lower() != "true":
            return OrjsonResponse(
                {
                    "error": "Benchmark endpoint disabled. Set FFBB_ENABLE_BENCHMARK=true to enable."
                },
                status_code=403,
            )
        try:
            result = await run_benchmark()
            return OrjsonResponse(result, status_code=201)
        except Exception as e:
            logger.exception("Benchmark failed")
            return OrjsonResponse(
                {"error": str(e), "error_type": type(e).__name__}, status_code=500
            )

    @mcp.custom_route("/docs", methods=["GET"])  # type: ignore[untyped-decorator]
    async def docs(request: Request) -> Response:
        return RedirectResponse("/docs/")

    @mcp.custom_route("/docs/", methods=["GET"])  # type: ignore[untyped-decorator]
    async def docs_slash(request: Request) -> Response:
        local_doc = _WEBSITE_DIR / "docs" / "index.html"
        if local_doc.exists():
            return HTMLResponse(
                content=local_doc.read_text(encoding="utf-8"), status_code=200
            )
        return RedirectResponse(
            "https://github.com/nickdesi/FFBB-MCP-Server/tree/main/docs"
        )

    @mcp.custom_route("/docs/{path:path}", methods=["GET"])  # type: ignore[untyped-decorator]
    async def docs_wildcard(request: Request) -> Response:
        path = request.path_params.get("path", "")
        docs_root = (_WEBSITE_DIR / "docs").resolve()
        try:
            local_doc = (docs_root / path).resolve()
            if docs_root not in local_doc.parents and local_doc != docs_root:
                return Response("Forbidden", status_code=403)
        except Exception:
            return Response("Not Found", status_code=404)
        if local_doc.exists() and local_doc.is_file():
            if local_doc.suffix == ".html":
                return HTMLResponse(
                    content=local_doc.read_text(encoding="utf-8"), status_code=200
                )
            return FileResponse(local_doc)
        return RedirectResponse(
            f"https://github.com/nickdesi/FFBB-MCP-Server/blob/main/docs/{path}"
        )

    @mcp.custom_route("/logo.webp", methods=["GET"])  # type: ignore[untyped-decorator]
    async def logo(request: Request) -> Response:
        return _logo_response()

    @mcp.custom_route("/favicon.ico", methods=["GET"])  # type: ignore[untyped-decorator]
    async def favicon(request: Request) -> Response:
        return _logo_response()

    @mcp.custom_route("/css/style.css", methods=["GET"])  # type: ignore[untyped-decorator]
    async def style_css(request: Request) -> Response:
        css_path = _WEBSITE_DIR / "css" / "style.css"
        if css_path.exists():
            return FileResponse(css_path, media_type="text/css")
        return Response("/* CSS non trouvé */", status_code=404)

    @mcp.custom_route("/robots.txt", methods=["GET"])  # type: ignore[untyped-decorator]
    async def robots_txt(request: Request) -> Response:
        return PlainTextResponse(_build_robots_txt())

    @mcp.custom_route("/sitemap.xml", methods=["GET"])  # type: ignore[untyped-decorator]
    async def sitemap_xml(request: Request) -> Response:
        return Response(_build_sitemap_xml(), media_type="application/xml")

    @mcp.custom_route("/cache/warmup", methods=["POST"])  # type: ignore[untyped-decorator]
    async def cache_warmup_post(request: Request) -> Response:
        """Déclenche le préchauffage du cache."""
        try:
            body = await request.json()
        except Exception:
            body = {}

        organisme_ids = body.get("organisme_ids") if isinstance(body, dict) else None
        sync_mode = body.get("sync", False) if isinstance(body, dict) else False

        if sync_mode:
            from .services.warmup import warmup_cache_service

            res = await warmup_cache_service(organisme_ids=organisme_ids)
            return OrjsonResponse(res, status_code=200)
        else:
            from .services.warmup import warmup_cache_service

            task = asyncio.create_task(
                warmup_cache_service(organisme_ids=organisme_ids)
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
            return OrjsonResponse(
                {
                    "status": "accepted",
                    "message": "Le préchauffage du cache a été déclenché en tâche de fond.",
                },
                status_code=202,
            )

    @mcp.custom_route("/cache/warmup", methods=["GET"])  # type: ignore[untyped-decorator]
    async def cache_warmup_get(request: Request) -> Response:
        """Informations sur l'endpoint de préchauffage du cache."""
        return OrjsonResponse(
            {
                "endpoint": "/cache/warmup",
                "methods": ["POST", "GET"],
                "description": "Préchauffe proactivement le cache FFBB pour les clubs favoris.",
                "usage_post": "POST {'organisme_ids': ['123', '456'], 'sync': false}",
                "env_var_config": "FFBB_WARMUP_ORGANISMES",
            }
        )

    @mcp.custom_route("/", methods=["GET"])  # type: ignore[untyped-decorator]
    async def index(request: Request) -> Response:
        return HTMLResponse(content=_build_index_html(), status_code=200)
