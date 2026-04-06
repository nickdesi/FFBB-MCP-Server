"""Tests d'intégration pour le serveur MCP FFBB refactoré."""

import numbers

import pytest
from mcp.server.fastmcp import FastMCP

from ffbb_mcp.server import (
    _build_index_html,
    _build_robots_txt,
    _build_sitemap_xml,
    _get_public_base_url,
    ffbb_version,
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
        "ffbb_version",
        "ffbb_search",
        "ffbb_bilan",
        "ffbb_team_summary",
        "ffbb_get",
        "ffbb_club",
        "ffbb_lives",
        "ffbb_saisons",
        "ffbb_resolve_team",
    ]

    for expected_name in expected:
        assert expected_name in tool_names, (
            f"L'outil '{expected_name}' est manquant dans l'enregistrement mcp."
        )


@pytest.mark.asyncio
async def test_ffbb_version_contract():
    """Vérifie le contrat de sortie de ffbb_version (dont cache_ttls)."""
    data = await ffbb_version()

    # Champs de base
    assert isinstance(data.get("package_version"), str) and data["package_version"], (
        "package_version doit être une chaîne non vide",
    )
    assert isinstance(data.get("python_version"), str) and data["python_version"], (
        "python_version doit être une chaîne non vide",
    )

    # cache_ttls doit être un dict avec des valeurs numériques
    cache_ttls = data.get("cache_ttls")
    assert isinstance(cache_ttls, dict), "cache_ttls doit être un dictionnaire"
    for key, value in cache_ttls.items():
        assert isinstance(value, numbers.Number), (
            f"cache_ttls['{key}'] doit être numérique (secondes)"
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

    assert 'meta name="description"' in html
    assert 'rel="icon" type="image/webp"' in html
    assert "FFBB MCP Server" in html


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
