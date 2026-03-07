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
        "get_lives",
        "get_saisons",
        "get_competition",
        "get_poule",
        "get_organisme",
        "get_equipes_club",
        "get_classement",
        "search_competitions",
        "search_organismes",
        "search_salles",
        "search_rencontres",
        "search_pratiques",
        "search_terrains",
        "search_tournois",
        "search_multi",
        "get_calendrier_club",
        "version",
    ]

    for expected_name in expected:
        assert expected_name in tool_names, (
            f"L'outil '{expected_name}' est manquant dans l'enregistrement mcp."
        )


@pytest.mark.asyncio
async def test_schemas_instantiation():
    """Vérifie que les Pydantic Models peuvent être instanciés correctement."""
    from ffbb_mcp.schemas import SearchInput

    # Doit valider avec l'alias "nom" (via validation_alias)
    si_nom = SearchInput(nom="Vichy")
    assert si_nom.name == "Vichy"

    # Doit valider avec l'alias "query" (via validation_alias)
    si_query = SearchInput(query="Vichy")
    assert si_query.name == "Vichy"


@pytest.mark.asyncio
async def test_server_tool_signatures():
    """Vérifie que les outils ont des signatures aplaties."""
    tools = await mcp.list_tools()

    # Recherche d'un outil spécifique pour inspecter ses arguments
    tool = next(t for t in tools if t.name == "get_organisme")

    # Dans FastMCP, les paramètres sont dans inputSchema
    props = tool.inputSchema.get("properties", {})
    assert "organisme_id" in props, "organisme_id devrait être un argument direct"
    assert "params" not in props, "L'argument 'params' ne devrait plus exister"
