"""Tests d'intégration pour le serveur MCP FFBB refactoré."""

import pytest
from mcp.server.fastmcp import FastMCP

from ffbb_mcp.server import mcp


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
