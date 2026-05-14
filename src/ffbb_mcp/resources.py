"""Définition des Resources MCP (Endpoints URI)."""

import json
from typing import Any

from .utils import prune_payload


async def _resource_to_json(service_coro) -> str:
    """Exécute un service et retourne son JSON pruné avec gestion d'erreurs."""
    from .services import handle_api_error

    try:
        data = await service_coro
        return json.dumps(prune_payload(data), default=str)
    except Exception as e:
        raise handle_api_error(e) from e


def register_resources(mcp: Any) -> None:
    """Enregistre les ressources sur l'instance FastMCP."""

    # FIX: toutes les resources passent désormais par le service layer
    # au lieu d'appeler le client directement.
    # Bénéfices : cache TTL partagé avec les tools, metrics enregistrées,
    # déduplication inflight, error handling cohérent.

    @mcp.resource("ffbb://saisons")
    async def resource_saisons() -> str:
        """Liste des saisons FFBB au format JSON."""
        from .services import get_saisons_service

        return await _resource_to_json(get_saisons_service())

    @mcp.resource("ffbb://competition/{competition_id}")
    async def resource_competition(competition_id: int) -> str:
        """Détails d'une compétition au format JSON."""
        from .services import get_competition_service

        return await _resource_to_json(get_competition_service(competition_id))

    @mcp.resource("ffbb://poule/{poule_id}")
    async def resource_poule(poule_id: int) -> str:
        """Détails d'une poule au format JSON."""
        from .services import get_poule_service

        return await _resource_to_json(get_poule_service(poule_id))

    @mcp.resource("ffbb://organisme/{organisme_id}")
    async def resource_organisme(organisme_id: int) -> str:
        """Détails d'un organisme/club au format JSON."""
        from .services import get_organisme_service

        return await _resource_to_json(get_organisme_service(organisme_id))
