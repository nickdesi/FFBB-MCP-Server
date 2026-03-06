import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .prompts import register_prompts
from .resources import register_resources
from .schemas import (
    CalendrierClubInput,
    CompetitionIdInput,
    OrganismeIdInput,
    PouleIdInput,
    SaisonsInput,
    SearchInput,
)
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
async def ffbb_get_saisons(params: SaisonsInput) -> list[dict[str, Any]]:
    """Liste des saisons (filtre actif possible)."""
    return await get_saisons_service(params)

# ---------------------------------------------------------------------------
# Outils MCP — Détails par ID
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_competition(params: CompetitionIdInput) -> dict[str, Any]:
    """Détails d'une compétition par ID."""
    return await get_competition_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_poule(params: PouleIdInput) -> dict[str, Any]:
    """Détails d'une poule/groupe par ID (classement, matchs)."""
    return await get_poule_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_organisme(params: OrganismeIdInput) -> dict[str, Any]:
    """Informations détaillées d'un club/organisme (adresse, équipes...)."""
    return await get_organisme_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_equipes_club(params: OrganismeIdInput) -> list[dict[str, Any]]:
    """Récupère uniquement la liste des équipes engagées par un club/organisme."""
    return await ffbb_equipes_club_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_classement(params: PouleIdInput) -> list[dict[str, Any]]:
    """Récupère uniquement le classement d'une poule/groupe (sans les matchs)."""
    return await ffbb_get_classement_service(params)

# ---------------------------------------------------------------------------
# Outils MCP — Recherche
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_competitions(params: SearchInput) -> list[dict[str, Any]]:
    """Recherche des compétitions FFBB par nom."""
    return await search_competitions_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_organismes(params: SearchInput) -> list[dict[str, Any]]:
    """Recherche des clubs/organismes FFBB par nom."""
    return await search_organismes_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_salles(params: SearchInput) -> list[dict[str, Any]]:
    """Recherche des salles de basket par nom/ville."""
    return await search_salles_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_rencontres(params: SearchInput) -> list[dict[str, Any]]:
    """Recherche des rencontres (matchs) FFBB par nom d'équipe ou de compétition."""
    return await search_rencontres_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_pratiques(params: SearchInput) -> list[dict[str, Any]]:
    """Recherche des pratiques de basketball (3x3, 5x5, VxE, etc.)."""
    return await search_pratiques_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_terrains(params: SearchInput) -> list[dict[str, Any]]:
    """Recherche des terrains de basketball par nom ou ville."""
    return await search_terrains_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_tournois(params: SearchInput) -> list[dict[str, Any]]:
    """Recherche des tournois de basketball."""
    return await search_tournois_service(params)

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_multi_search(params: SearchInput) -> list[dict[str, Any]]:
    """Recherche globale sur tous les types FFBB en une seule requête."""
    return await multi_search_service(params)

# ---------------------------------------------------------------------------
# Outils MCP — Aggrégation
# ---------------------------------------------------------------------------

@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_calendrier_club(params: CalendrierClubInput) -> dict[str, Any]:
    """Récupère le calendrier (prochains matchs) d'un club et de ses équipes."""
    return await get_calendrier_club_service(params)

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
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "9123"))
        logger.info(f"Démarrage du serveur MCP FFBB en mode SSE sur {host}:{port} derrière un proxy...")
        
        app = mcp.sse_app()
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
