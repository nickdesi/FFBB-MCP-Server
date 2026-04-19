import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from .metrics import generate_prometheus_metrics

logger = logging.getLogger("ffbb-mcp")

# Paths for static assets
_STATIC_DIR = Path(__file__).parent.parent.parent / "website"
_INDEX_HTML_PATH = _STATIC_DIR / "index.html"
_ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"
_LOGO_PATH = _ASSETS_DIR / "logo_ffbb_mcp.webp"
_FAVICON_PATH = _ASSETS_DIR / "favicon.ico"
_CSS_PATH = _STATIC_DIR / "css" / "style.css"
_REMOTE_LOGO_URL = "https://raw.githubusercontent.com/nickdesi/FFBB-MCP-Server/refs/heads/main/assets/logo_ffbb_mcp.webp"


async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok", "service": "ffbb-mcp"})


async def metrics(request: Request) -> Response:
    return PlainTextResponse(generate_prometheus_metrics(), media_type="text/plain")


async def logo(request: Request) -> Response:
    if _LOGO_PATH.exists():
        return FileResponse(_LOGO_PATH, media_type="image/webp")
    return RedirectResponse(_REMOTE_LOGO_URL)


async def favicon(request: Request) -> Response:
    if _FAVICON_PATH.exists():
        return FileResponse(_FAVICON_PATH, media_type="image/x-icon")
    return RedirectResponse(_REMOTE_LOGO_URL)


async def style_css(request: Request) -> Response:
    if _CSS_PATH.exists():
        return FileResponse(_CSS_PATH, media_type="text/css")
    return PlainTextResponse("/* CSS non trouvé */", status_code=404)


async def robots_txt(request: Request) -> Response:
    public_url = request.app.state.public_url
    content = f"User-agent: *\nAllow: /\n\nSitemap: {public_url}/sitemap.xml\n"
    return PlainTextResponse(content)


async def sitemap_xml(request: Request) -> Response:
    public_url = request.app.state.public_url
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{public_url}/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>"""
    return Response(content=content, media_type="application/xml")


async def index(request: Request) -> Response:
    if _INDEX_HTML_PATH.exists():
        return FileResponse(_INDEX_HTML_PATH, media_type="text/html")
    # Fallback minimal si l'asset manque
    return HTMLResponse(
        "<h1>FFBB MCP Server</h1><p>Running. Use an MCP client to connect.</p>"
    )




def register_http_routes(mcp: FastMCP) -> None:
    """Enregistre toutes les routes HTTP custom sur le serveur FastMCP."""
    mcp.custom_route("/health", methods=["GET"])(health)
    mcp.custom_route("/metrics", methods=["GET"])(metrics)
    mcp.custom_route("/logo", methods=["GET"])(logo)
    mcp.custom_route("/favicon.ico", methods=["GET"])(favicon)
    mcp.custom_route("/css/style.css", methods=["GET"])(style_css)
    mcp.custom_route("/robots.txt", methods=["GET"])(robots_txt)
    mcp.custom_route("/sitemap.xml", methods=["GET"])(sitemap_xml)
    mcp.custom_route("/", methods=["GET"])(index)
