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
        "ffbb_get_lives",
        "ffbb_get_saisons",
        "ffbb_get_competition",
        "ffbb_get_poule",
        "ffbb_get_organisme",
        "ffbb_equipes_club",
        "ffbb_get_classement",
        "ffbb_search_competitions",
        "ffbb_search_organismes",
        "ffbb_search_salles",
        "ffbb_search_rencontres",
        "ffbb_search_pratiques",
        "ffbb_search_terrains",
        "ffbb_search_tournois",
        "ffbb_multi_search",
        "ffbb_calendrier_club",
    ]
    
    for expected_name in expected:
        assert expected_name in tool_names, f"L'outil '{expected_name}' est manquant dans l'enregistrement mcp."


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
    tool = next(t for t in tools if t.name == "ffbb_get_organisme")
    
    # Dans FastMCP, les paramètres sont dans inputSchema
    props = tool.inputSchema.get("properties", {})
    assert "organisme_id" in props, "organisme_id devrait être un argument direct"
    assert "params" not in props, "L'argument 'params' ne devrait plus exister"
