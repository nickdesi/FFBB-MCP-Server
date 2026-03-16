"""Tests d'intégration pour le serveur MCP FFBB refactoré."""

import pytest
from mcp.server.fastmcp import FastMCP

from ffbb_mcp.server import (
    _build_index_html,
    _build_robots_txt,
    _build_sitemap_xml,
    _get_public_base_url,
    mcp,
)


def test_server_initialization():
    """Vérifie que FastMCP est bien initialisé."""
    assert isinstance(mcp, FastMCP)
    assert mcp.name == "FFBB MCP Server"


@pytest.mark.asyncio
async def test_server_tools_importable():
    """Vérifie que les outils sont bien enregistrés via FastMCP."""
    tools = await mcp.list_tools()

    # Afin de tester de façon robuste et compatible FastMCP
    tool_names = [tool.name for tool in tools]

    expected = [
        "ffbb_search",
        "ffbb_get",
        "ffbb_club",
        "ffbb_lives",
        "ffbb_saisons",
    ]

    for expected_name in expected:
        assert expected_name in tool_names, (
            f"L'outil '{expected_name}' est manquant dans l'enregistrement mcp."
        )


@pytest.mark.asyncio
async def test_server_tool_signatures():
    """Vérifie que les outils ont des signatures aplaties."""
    tools = await mcp.list_tools()

    # Recherche d'un outil spécifique pour inspecter ses arguments
    tool = next(t for t in tools if t.name == "ffbb_get")

    # Dans FastMCP, les paramètres sont dans inputSchema
    props = tool.inputSchema.get("properties", {})
    assert "id" in props, "id devrait être un argument direct"
    assert "type" in props, "type devrait être un argument direct"


def test_public_base_url_strips_mcp_suffix(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://ffbb.desimone.fr/mcp/")

    assert _get_public_base_url() == "https://ffbb.desimone.fr"


def test_index_html_contains_seo_metadata(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://ffbb.desimone.fr")

    html = _build_index_html()

    assert (
        'rel="icon" type="image/webp" href="https://ffbb.desimone.fr/logo.webp"' in html
    )
    assert 'meta name="description"' in html
    assert 'property="og:image" content="https://ffbb.desimone.fr/logo.webp"' in html
    assert 'link rel="canonical" href="https://ffbb.desimone.fr/"' in html


def test_robots_txt_contains_sitemap(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://ffbb.desimone.fr/mcp")

    robots = _build_robots_txt()

    assert "User-agent: *" in robots
    assert "Allow: /" in robots
    assert "Sitemap: https://ffbb.desimone.fr/sitemap.xml" in robots


def test_sitemap_xml_uses_canonical_root(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://ffbb.desimone.fr/mcp/")

    sitemap = _build_sitemap_xml()

    assert "<loc>https://ffbb.desimone.fr/</loc>" in sitemap
    assert "<changefreq>weekly</changefreq>" in sitemap
