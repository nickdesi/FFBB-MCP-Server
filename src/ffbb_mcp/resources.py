"""Définition des Resources MCP (Endpoints URI)."""

import json


def register_resources(mcp):
    """Enregistre les ressources sur l'instance FastMCP."""

    # FIX: toutes les resources passent désormais par le service layer
    # au lieu d'appeler le client directement.
    # Bénéfices : cache TTL partagé avec les tools, metrics enregistrées,
    # déduplication inflight, error handling cohérent.

    @mcp.resource("ffbb://saisons")
    async def resource_saisons() -> str:
        """Liste des saisons FFBB au format JSON."""
        from .services import get_saisons_service

        try:
            data = await get_saisons_service()
            return json.dumps(data, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, default=str)

    @mcp.resource("ffbb://competition/{competition_id}")
    async def resource_competition(competition_id: int) -> str:
        """Détails d'une compétition au format JSON."""
        from .services import get_competition_service

        try:
            data = await get_competition_service(competition_id)
            return json.dumps(data, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, default=str)

    @mcp.resource("ffbb://poule/{poule_id}")
    async def resource_poule(poule_id: int) -> str:
        """Détails d'une poule au format JSON."""
        from .services import get_poule_service

        try:
            data = await get_poule_service(poule_id)
            return json.dumps(data, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, default=str)

    @mcp.resource("ffbb://organisme/{organisme_id}")
    async def resource_organisme(organisme_id: int) -> str:
        """Détails d'un organisme/club au format JSON."""
        from .services import get_organisme_service

        try:
            data = await get_organisme_service(organisme_id)
            return json.dumps(data, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, default=str)
