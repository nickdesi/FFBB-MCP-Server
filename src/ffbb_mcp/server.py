import logging
import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AliasChoices, Field

from .prompts import register_prompts
from .resources import register_resources
from .services import (
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    get_calendrier_club_service,
    get_competition_service,
    get_lives_service,
    get_organisme_service,
    get_poule_service,
    get_saisons_service,
    multi_search_service,
    search_competitions_service,
    search_organismes_service,
    search_pratiques_service,
    search_rencontres_service,
    search_salles_service,
    search_terrains_service,
    search_tournois_service,
)

logger = logging.getLogger("ffbb-mcp")

# Read-only annotations (all FFBB tools are read-only)
_READONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

# ---------------------------------------------------------------------------
# Initialisation FastMCP
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "FFBB MCP Server",
    instructions=(
        "Ce serveur expose les données de la Fédération Française de Basketball "
        "(FFBB). "
        "Tu peux consulter les matchs en direct, le calendrier des rencontres, "
        "les résultats, les compétitions, les clubs et les salles de sport.\n\n"
        "Workflow recommandé :\n"
        "1. Utilise `ffbb_multi_search` pour une exploration générale\n"
        "2. Ou `ffbb_search_*` pour cibler un type précis "
        "(compétitions, clubs, matchs, salles, pratiques, terrains, tournois)\n"
        "3. Puis `ffbb_get_*` (ou ffbb_calendrier_club) avec l'ID obtenu pour les détails complets\n\n"
        "Tous les outils renvoient du JSON structuré."
    ),
    dependencies=["mcp", "ffbb-api-client-v3"],
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False, 
        allowed_hosts=["*"], 
        allowed_origins=["*"],
    ),
)


# ---------------------------------------------------------------------------
# Outils MCP — Données en direct
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_lives() -> list[dict[str, Any]]:
    """Matchs en cours (scores live).

    Returns:
        list[dict]: Liste de matchs en direct.
    """
    return await get_lives_service()

# ---------------------------------------------------------------------------
# Outils MCP — Saisons
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_saisons(
    active_only: bool = False
) -> list[dict[str, Any]]:
    """Liste des saisons (filtre actif possible)."""
    return await get_saisons_service(active_only=active_only)

# ---------------------------------------------------------------------------
# Outils MCP — Détails par ID
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_competition(
    competition_id: Annotated[int | str, Field(validation_alias=AliasChoices("competition_id", "id"))]
) -> dict[str, Any]:
    """Détails d'une compétition par ID."""
    return await get_competition_service(competition_id=competition_id)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_poule(
    poule_id: Annotated[int | str, Field(validation_alias=AliasChoices("poule_id", "id"))]
) -> dict[str, Any]:
    """Détails d'une poule/groupe par ID (classement, matchs)."""
    return await get_poule_service(poule_id=poule_id)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_organisme(
    organisme_id: Annotated[int | str, Field(validation_alias=AliasChoices("organisme_id", "id", "club_id"))]
) -> dict[str, Any]:
    """Informations détaillées d'un club/organisme (adresse, équipes...)."""
    return await get_organisme_service(organisme_id=organisme_id)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_equipes_club(
    organisme_id: Annotated[int | str, Field(validation_alias=AliasChoices("organisme_id", "id", "club_id"))],
    filtre: str | None = None
) -> list[dict[str, Any]]:
    """Récupère uniquement la liste des équipes engagées par un club/organisme."""
    return await ffbb_equipes_club_service(organisme_id=organisme_id, filtre=filtre)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_classement(
    poule_id: Annotated[int | str, Field(validation_alias=AliasChoices("poule_id", "id"))]
) -> list[dict[str, Any]]:
    """Récupère uniquement le classement d'une poule/groupe (sans les matchs)."""
    return await ffbb_get_classement_service(poule_id=poule_id)

# ---------------------------------------------------------------------------
# Outils MCP — Recherche
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_competitions(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))]
) -> list[dict[str, Any]]:
    """Recherche des compétitions FFBB par nom (paramètres: nom ou query)."""
    return await search_competitions_service(nom=nom)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_organismes(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))]
) -> list[dict[str, Any]]:
    """Recherche des clubs/organismes FFBB par nom (paramètres: nom ou query)."""
    return await search_organismes_service(nom=nom)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_salles(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))]
) -> list[dict[str, Any]]:
    """Recherche des salles de basket par nom/ville (paramètres: nom ou query)."""
    return await search_salles_service(nom=nom)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_rencontres(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))]
) -> list[dict[str, Any]]:
    """Recherche des rencontres (matchs) FFBB (paramètres: nom ou query)."""
    return await search_rencontres_service(nom=nom)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_pratiques(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))]
) -> list[dict[str, Any]]:
    """Recherche des pratiques de basketball (paramètres: nom ou query)."""
    return await search_pratiques_service(nom=nom)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_terrains(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))]
) -> list[dict[str, Any]]:
    """Recherche des terrains de basketball (paramètres: nom ou query)."""
    return await search_terrains_service(nom=nom)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_tournois(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))]
) -> list[dict[str, Any]]:
    """Recherche des tournois de basketball (paramètres: nom ou query)."""
    return await search_tournois_service(nom=nom)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_multi_search(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))]
) -> list[dict[str, Any]]:
    """Recherche globale FFBB (paramètres: nom ou query)."""
    return await multi_search_service(nom=nom)

# ---------------------------------------------------------------------------
# Outils MCP — Aggrégation
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_calendrier_club(
    club_name: Annotated[str | None, Field(validation_alias=AliasChoices("club_name", "nom"))] = None,
    organisme_id: Annotated[int | str | None, Field(validation_alias=AliasChoices("organisme_id", "club_id", "id"))] = None,
    categorie: str | None = None
) -> list[dict[str, Any]]:
    """Récupère le calendrier (prochains matchs) d'un club (via club_name ou organisme_id)."""
    return await get_calendrier_club_service(
        club_name=club_name, 
        organisme_id=organisme_id, 
        categorie=categorie
    )

# ---------------------------------------------------------------------------
# Injections 
# ---------------------------------------------------------------------------

register_prompts(mcp)
register_resources(mcp)

# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main() -> None:
    """Lance le serveur MCP FFBB."""
    mode = os.environ.get("MCP_MODE", "stdio").lower()
    
    if mode == "sse":
        import uvicorn
        from fastapi import FastAPI
        
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "9123"))
        
        # Le transport SSE de FastMCP renvoie une application FastAPI
        # On la monte sous le path /mcp pour correspondre à l'URL souhaitée
        mcp_app = mcp.sse_app()
        app = FastAPI()
        app.mount("/mcp", mcp_app)
        
        logger.info(f"Démarrage du serveur MCP FFBB en mode SSE sur {host}:{port}...")
        logger.info(f"Endpoint disponible sur : http://{host}:{port}/mcp/sse")
        
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
            proxy_headers=True,
            forwarded_allow_ips="*"
        )
    else:
        logger.info("Démarrage du serveur MCP FFBB en mode stdio...")
        mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
