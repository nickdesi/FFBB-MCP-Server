"""Définition des Resources MCP (Endpoints URI)."""

import json

from .client import get_client_async
from .utils import serialize_model


def register_resources(mcp):
    """Enregistre les ressources sur l'instance FastMCP."""

    @mcp.resource("ffbb://saisons")
    async def resource_saisons() -> str:
        """Liste des saisons FFBB au format JSON."""
        client = await get_client_async()
        saisons = await client.get_saisons_async()
        return json.dumps(
            [serialize_model(s) for s in saisons] if saisons else [],
            default=str,
        )

    @mcp.resource("ffbb://competition/{competition_id}")
    async def resource_competition(competition_id: int) -> str:
        """Détails d'une compétition au format JSON."""
        client = await get_client_async()
        comp = await client.get_competition_async(competition_id)
        return json.dumps(serialize_model(comp) or {}, default=str)

    @mcp.resource("ffbb://poule/{poule_id}")
    async def resource_poule(poule_id: int) -> str:
        """Détails d'une poule au format JSON."""
        client = await get_client_async()
        poule = await client.get_poule_async(poule_id)
        return json.dumps(serialize_model(poule) or {}, default=str)

    @mcp.resource("ffbb://organisme/{organisme_id}")
    async def resource_organisme(organisme_id: int) -> str:
        """Détails d'un organisme/club au format JSON."""
        client = await get_client_async()
        org = await client.get_organisme_async(organisme_id)
        return json.dumps(serialize_model(org) or {}, default=str)
