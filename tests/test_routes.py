"""Tests unitaires pour le module routes.py de FFBB MCP server."""

from pathlib import Path
from unittest.mock import patch
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


def test_docs_redirect(client):
    """Teste la redirection de /docs vers /docs/."""
    response = client.get("/docs", follow_redirects=False)
    assert response.status_code in (301, 302, 307)
    assert response.headers["location"] == "/docs/"


def test_docs_slash_local(client, tmp_path):
    """Teste l'accès à /docs/ (index de la doc)."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    index_file = docs_dir / "index.html"
    index_file.write_text("Mock index", encoding="utf-8")

    with patch("ffbb_mcp.routes._WEBSITE_DIR", new=tmp_path):
        response = client.get("/docs/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


def test_docs_wildcard_local_html(client, tmp_path):
    """Teste l'accès à un fichier html de doc existant localement."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    html_file = docs_dir / "404.html"
    html_file.write_text("Mock 404", encoding="utf-8")

    with patch("ffbb_mcp.routes._WEBSITE_DIR", new=tmp_path):
        response = client.get("/docs/404.html")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


def test_docs_wildcard_local_non_html(client, tmp_path):
    """Teste l'accès à un fichier non html existant localement."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    css_file = docs_dir / "vp-icons.css"
    css_file.write_text("body {}", encoding="utf-8")

    with patch("ffbb_mcp.routes._WEBSITE_DIR", new=tmp_path):
        response = client.get("/docs/vp-icons.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]


def test_docs_slash_redirect(client):
    """Teste la redirection de /docs/ vers GitHub quand index.html est absent."""
    with patch("ffbb_mcp.routes._WEBSITE_DIR", new=Path("/nonexistent_path_docs")):
        response = client.get("/docs/", follow_redirects=False)
        assert response.status_code in (301, 302, 307)
        assert urlparse(response.headers["location"]).hostname == "github.com"


def test_docs_wildcard_html_redirect(client):
    """Teste la redirection vers GitHub pour un fichier html inexistant localement."""
    with patch("ffbb_mcp.routes._WEBSITE_DIR", new=Path("/nonexistent_path_docs")):
        response = client.get("/docs/404.html", follow_redirects=False)
        assert response.status_code in (301, 302, 307)
        assert urlparse(response.headers["location"]).hostname == "github.com"


def test_docs_wildcard_css_redirect(client):
    """Teste la redirection vers GitHub pour un fichier css inexistant localement."""
    with patch("ffbb_mcp.routes._WEBSITE_DIR", new=Path("/nonexistent_path_docs")):
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


def test_next_match_api_route(client):
    """Teste l'endpoint REST /api/v1/next-match."""
    with patch("ffbb_mcp.services.club.ffbb_next_match_service") as mock_next_match:
        mock_next_match.return_value = {
            "status": "ok",
            "match": {
                "date": "2026-09-19T15:30:00+02:00",
                "adversaire": "TEST ADVERSAIRE",
                "domicile": True,
            },
        }
        response = client.get("/api/v1/next-match?organisme_id=9326&categorie=SEM1")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["match"]["adversaire"] == "TEST ADVERSAIRE"


def test_club_matches_api_route(client):
    """Teste l'endpoint REST /api/v1/club/{organisme_id}/matches."""
    from unittest.mock import AsyncMock, MagicMock

    mock_client = MagicMock()
    mock_org = MagicMock()
    mock_org.nom = "STADE CLERMONTOIS BASKET AUVERGNE"
    mock_org.logo = MagicMock(id="logo123")

    mock_eng = MagicMock()
    mock_eng.idPoule = MagicMock(id=101)
    mock_eng.idCompetition = MagicMock(nom="Pré nationale masculine")
    mock_org.engagements = [mock_eng]

    mock_poule = MagicMock()
    mock_rencontre = MagicMock()
    mock_rencontre.id = "m123"
    mock_rencontre.nomEquipe1 = "SCBA"
    mock_rencontre.nomEquipe2 = "CLERMONT BASKET"
    mock_rencontre.idOrganismeEquipe1 = "9326"
    mock_rencontre.idOrganismeEquipe2 = "5555"
    mock_rencontre.date = "2026-10-10"
    mock_rencontre.horaire = "20h30"
    mock_rencontre.salle = "salle_1"
    mock_poule.rencontres = [mock_rencontre]

    mock_client.get_organisme_async = AsyncMock(return_value=mock_org)
    mock_client.get_poule_async = AsyncMock(return_value=mock_poule)

    async def mock_enrich_salles(matches):
        for m in matches:
            if m.get("salle") == "salle_1":
                m["adresse_salle"] = (
                    "GYMNASE THEVENET - 9 Rue Albert Mallet, 63000 Clermont-Ferrand"
                )

    with (
        patch("ffbb_mcp.client.get_client_async", AsyncMock(return_value=mock_client)),
        patch(
            "ffbb_mcp.services.salle._enrich_matches_with_salle_details",
            side_effect=mock_enrich_salles,
        ),
    ):
        response = client.get("/api/v1/club/9326/matches")
        assert response.status_code == 200
        data = response.json()
        assert data["organisme_id"] == 9326
        assert data["count"] == 1
        assert len(data["matches"]) == 1
        assert data["matches"][0]["ffbbMatchId"] == "m123"
        assert data["matches"][0]["team"] == "SENIOR M1"
        assert data["matches"][0]["isHome"] is True
        assert (
            data["matches"][0]["location"]
            == "GYMNASE THEVENET - 9 Rue Albert Mallet, 63000 Clermont-Ferrand"
        )
