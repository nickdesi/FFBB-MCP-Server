"""Tests unitaires pour le module routes.py de FFBB MCP server."""

from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

import pytest
from starlette.testclient import TestClient

from ffbb_mcp.app_factory import create_app
from ffbb_mcp.server import mcp


@pytest.fixture
def client():
    # Configuration par défaut
    app = create_app(mcp, allowed_origins=["*"])
    return TestClient(app)


def test_index_route(client):
    """Teste l'accès à la page d'accueil."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "FFBB MCP" in response.text or "Site en maintenance" in response.text


def test_health_route(client):
    """Teste l'endpoint /health."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "ffbb-mcp"
    assert "status" in data
    assert "uptime_seconds" in data
    assert "api_calls_total" in data


def test_metrics_route(client):
    """Teste l'endpoint /metrics pour Prometheus."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "ffbb_uptime_seconds" in response.text


def test_metrics_json_route(client):
    """Teste l'endpoint /metrics.json."""
    response = client.get("/metrics.json")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "ffbb-mcp"
    assert "uptime_seconds" in data


def test_dashboard_route(client):
    """Teste l'endpoint /dashboard."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "FFBB" in response.text


def test_benchmark_get_route_disabled(client, monkeypatch):
    """Teste /benchmark quand le benchmark est désactivé par défaut."""
    monkeypatch.setenv("FFBB_ENABLE_BENCHMARK", "false")
    response = client.get("/benchmark")
    assert response.status_code == 200
    data = response.json()
    assert data["benchmark_enabled"] is False
    assert "hint" in data


def test_benchmark_get_route_enabled(client, monkeypatch):
    """Teste /benchmark quand le benchmark est activé."""
    monkeypatch.setenv("FFBB_ENABLE_BENCHMARK", "true")
    response = client.get("/benchmark")
    assert response.status_code == 200
    data = response.json()
    assert data["benchmark_enabled"] is True


def test_benchmark_post_route_disabled(client, monkeypatch):
    """Teste /benchmark/run quand le benchmark est désactivé."""
    monkeypatch.setenv("FFBB_ENABLE_BENCHMARK", "false")
    response = client.post("/benchmark/run")
    assert response.status_code == 403
    assert "disabled" in response.json()["error"]


@pytest.mark.asyncio
async def test_benchmark_post_route_enabled_success(client, monkeypatch):
    """Teste /benchmark/run avec succès quand il est activé."""
    monkeypatch.setenv("FFBB_ENABLE_BENCHMARK", "true")
    mock_run = {"success": True, "total_ms": 150.0, "steps": []}

    with patch(
        "ffbb_mcp.routes.run_benchmark", new_callable=AsyncMock, return_value=mock_run
    ) as mock_bench:
        response = client.post("/benchmark/run")
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        mock_bench.assert_called_once()


@pytest.mark.asyncio
async def test_benchmark_post_route_enabled_failure(client, monkeypatch):
    """Teste /benchmark/run en échec (exception levée)."""
    monkeypatch.setenv("FFBB_ENABLE_BENCHMARK", "true")

    with patch(
        "ffbb_mcp.routes.run_benchmark",
        new_callable=AsyncMock,
        side_effect=ValueError("Test Failure"),
    ) as mock_bench:
        response = client.post("/benchmark/run")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "Test Failure"
        mock_bench.assert_called_once()


def test_docs_redirect(client):
    """Teste la redirection de /docs vers /docs/."""
    response = client.get("/docs", follow_redirects=False)
    assert response.status_code in (301, 302, 307)
    assert response.headers["location"] == "/docs/"


def test_docs_slash_redirect(client):
    """Teste la redirection de /docs/ vers GitHub quand index.html est absent."""
    response = client.get("/docs/", follow_redirects=False)
    assert response.status_code in (301, 302, 307)
    assert urlparse(response.headers["location"]).hostname == "github.com"


def test_docs_wildcard_html_redirect(client):
    """Teste la redirection vers GitHub pour un fichier html inexistant localement."""
    response = client.get("/docs/404.html", follow_redirects=False)
    assert response.status_code in (301, 302, 307)
    assert urlparse(response.headers["location"]).hostname == "github.com"


def test_docs_wildcard_css_redirect(client):
    """Teste la redirection vers GitHub pour un fichier css inexistant localement."""
    response = client.get("/docs/vp-icons.css", follow_redirects=False)
    assert response.status_code in (301, 302, 307)
    assert urlparse(response.headers["location"]).hostname == "github.com"


def test_docs_wildcard_redirect_github(client):
    """Teste la redirection vers GitHub pour un fichier inexistant localement."""
    response = client.get("/docs/not-found-anywhere.html", follow_redirects=False)
    assert response.status_code in (301, 302, 307)
    assert urlparse(response.headers["location"]).hostname == "github.com"


def test_docs_wildcard_path_traversal_protection(client):
    """Teste la protection contre les attaques de type Path Traversal."""
    response = client.get("/docs/../../pyproject.toml")
    assert response.status_code in (403, 404)


def test_logo_webp(client):
    """Teste /logo.webp."""
    response = client.get("/logo.webp")
    assert response.status_code == 200
    assert "image/webp" in response.headers["content-type"]


def test_favicon_ico(client):
    """Teste /favicon.ico."""
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert "image/webp" in response.headers["content-type"]


def test_style_css(client):
    """Teste /css/style.css."""
    response = client.get("/css/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_robots_txt(client):
    """Teste /robots.txt."""
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "User-agent" in response.text


def test_sitemap_xml(client):
    """Teste /sitemap.xml."""
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<urlset" in response.text


def test_index_route_maintenance(client):
    """Teste l'accès à la page d'accueil en mode maintenance (index.html absent)."""
    with patch("ffbb_mcp.routes._WEBSITE_DIR", new=Path("/nonexistent_path_routes")):
        response = client.get("/")
        assert response.status_code == 200
        assert "Site en maintenance" in response.text


def test_logo_redirect_fallback(client):
    """Teste la redirection du logo si le fichier local n'existe pas."""
    with patch("ffbb_mcp.routes._LOGO_PATH", new=Path("/nonexistent_logo.webp")):
        response = client.get("/logo.webp", follow_redirects=False)
        assert response.status_code in (301, 302, 307)
        assert (
            response.headers["location"]
            == "https://raw.githubusercontent.com/nickdesi/FFBB-MCP-Server/main/assets/logo.webp"
        )


def test_style_css_not_found(client):
    """Teste l'endpoint CSS si le fichier CSS n'existe pas."""
    with patch("ffbb_mcp.routes._WEBSITE_DIR", new=Path("/nonexistent_path_css")):
        response = client.get("/css/style.css")
        assert response.status_code == 404
        assert "CSS non trouvé" in response.text


def test_find_website_dir():
    """Teste la détection du répertoire de site."""
    from ffbb_mcp.routes import _find_website_dir

    website_dir = _find_website_dir()
    assert isinstance(website_dir, Path)
    assert website_dir.exists()
