import logging
import traceback
from typing import Any, TypeVar

from ffbb_api_client_v3.helpers.multi_search_query_helper import generate_queries
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from .client import get_client_async
from .schemas import (
    CalendrierClubInput,
    CompetitionIdInput,
    OrganismeIdInput,
    PouleIdInput,
    SaisonsInput,
    SearchInput,
)
from .utils import serialize_model

logger = logging.getLogger("ffbb-mcp")

T = TypeVar("T")


def _handle_api_error(e: Exception) -> McpError:
    """Formatage cohérent des erreurs API pour tous les outils."""
    if isinstance(e, McpError):
        return e
    
    error_msg = str(e)
    logger.error(f"FFBB API Error: {error_msg}")
    logger.error(traceback.format_exc())

    return McpError(
        error=ErrorData(
            code=INTERNAL_ERROR,
            message=f"Erreur API FFBB: {error_msg}",
        )
    )


async def _safe_call(operation_name: str, coro) -> Any:
    """Exécute un appel API avec logging et error handling."""
    logger.info(f"Début exécution: {operation_name}")
    try:
        result = await coro
        logger.info(f"Succès: {operation_name}")
        return result
    except Exception as e:
        raise _handle_api_error(e) from e


# ---------------------------------------------------------------------------
# Services -- Données en direct
# ---------------------------------------------------------------------------

async def get_lives_service() -> list[dict]:
    client = await get_client_async()
    lives = await _safe_call("Lives (Matchs en cours)", client.get_lives_async())
    if not lives:
        return []
    return [serialize_model(live) for live in lives]


# ---------------------------------------------------------------------------
# Services -- Saisons
# ---------------------------------------------------------------------------

async def get_saisons_service(params: SaisonsInput) -> list[dict]:
    client = await get_client_async()
    saisons = await _safe_call(
        "Saisons", 
        client.get_saisons_async(active_only=params.active_only)
    )
    if not saisons:
        return []
    return [serialize_model(s) for s in saisons]


# ---------------------------------------------------------------------------
# Services -- Détails par ID
# ---------------------------------------------------------------------------

async def get_competition_service(params: CompetitionIdInput) -> dict:
    client = await get_client_async()
    comp = await _safe_call(
        f"Compétition {params.competition_id}",
        client.get_competition_async(competition_id=params.competition_id)
    )
    return serialize_model(comp) or {}

async def get_poule_service(params: PouleIdInput) -> dict:
    client = await get_client_async()
    poule = await _safe_call(
        f"Poule {params.poule_id}",
        client.get_poule_async(poule_id=params.poule_id)
    )
    return serialize_model(poule) or {}

async def get_organisme_service(params: OrganismeIdInput) -> dict:
    client = await get_client_async()
    org = await _safe_call(
        f"Organisme {params.organisme_id}",
        client.get_organisme_async(organisme_id=params.organisme_id)
    )
    return serialize_model(org) or {}

async def ffbb_equipes_club_service(params: OrganismeIdInput) -> list[dict[str, Any]]:
    client = await get_client_async()
    org = await _safe_call(
        f"Equipes club {params.organisme_id}",
        client.get_organisme_async(organisme_id=params.organisme_id)
    )
    if not org:
        return []
    data = serialize_model(org)
    raw = data.get("engagements", []) if isinstance(data, dict) else []
    flat: list[dict[str, Any]] = []
    club_nom = data.get("nom", "")
    for e in raw:
        comp = e.get("idCompetition", {}) or {}
        poule = e.get("idPoule", {}) or {}
        cat = comp.get("categorie", {}) or {}
        flat.append(
            {
                "engagement_id": e.get("id"),
                "nom_equipe": club_nom,
                "numero_equipe": None,
                "competition": comp.get("nom", ""),
                "competition_id": comp.get("id"),
                "competition_code": comp.get("code", ""),
                "poule_id": poule.get("id"),
                "sexe": comp.get("sexe", ""),
                "categorie": cat.get("code", ""),
                "type": comp.get("typeCompetition", ""),
                "niveau": comp.get("competition_origine_niveau"),
            }
        )
    return flat


async def ffbb_get_classement_service(params: PouleIdInput) -> list[dict[str, Any]]:
    client = await get_client_async()
    poule = await _safe_call(
        f"Classement poule {params.poule_id}",
        client.get_poule_async(poule_id=params.poule_id)
    )
    if not poule:
        return []
    data = serialize_model(poule)
    raw = data.get("classements", data.get("classement", []))
    if not isinstance(raw, list):
        raw = []
    flat: list[dict[str, Any]] = []
    for c in raw:
        eng = c.get("id_engagement", {}) or {}
        flat.append(
            {
                "position": c.get("position"),
                "equipe": eng.get("nom", ""),
                "numero_equipe": eng.get("numero_equipe", ""),
                "points": c.get("points"),
                "match_joues": c.get("match_joues"),
                "gagnes": c.get("gagnes"),
                "perdus": c.get("perdus"),
                "nuls": c.get("nuls"),
                "paniers_marques": c.get("paniers_marques"),
                "paniers_encaisses": c.get("paniers_encaisses"),
                "difference": c.get("difference"),
                "quotient": c.get("quotient"),
                "forfaits": c.get("nombre_forfaits"),
            }
        )
    return flat

# ---------------------------------------------------------------------------
# Services -- Recherche par type
# ---------------------------------------------------------------------------

async def _search_generic(operation: str, method_name: str, query: str) -> list[dict]:
    client = await get_client_async()
    method = getattr(client, method_name)
    results = await _safe_call(f"Recherche {operation}: {query}", method(query))
    if not results or not results.hits:
        return []
    return [serialize_model(hit) for hit in results.hits]

async def search_competitions_service(params: SearchInput) -> list[dict]:
    return await _search_generic("competitions", "search_competitions_async", params.name)

async def search_organismes_service(params: SearchInput) -> list[dict]:
    return await _search_generic("organismes", "search_organismes_async", params.name)

async def search_salles_service(params: SearchInput) -> list[dict]:
    return await _search_generic("salles", "search_salles_async", params.name)

async def search_rencontres_service(params: SearchInput) -> list[dict]:
    return await _search_generic("rencontres", "search_rencontres_async", params.name)

async def search_pratiques_service(params: SearchInput) -> list[dict]:
    return await _search_generic("pratiques", "search_pratiques_async", params.name)

async def search_terrains_service(params: SearchInput) -> list[dict]:
    return await _search_generic("terrains", "search_terrains_async", params.name)

async def search_tournois_service(params: SearchInput) -> list[dict]:
    return await _search_generic("tournois", "search_tournois_async", params.name)


# ---------------------------------------------------------------------------
# Services -- Recherche Multitypes & Agregation
# ---------------------------------------------------------------------------

async def multi_search_service(params: SearchInput) -> list[dict[str, Any]]:
    client = await get_client_async()
    queries = generate_queries(params.name)
    results = await _safe_call(
        f"Recherche multi-types: {params.name}",
        client.multi_search_async(queries=queries)
    )
    if not results or not results.results:
        return []

    output: list[dict[str, Any]] = []
    for res in results.results:
        if res.hits:
            category = res.index_uid
            for hit in res.hits:
                item = serialize_model(hit)
                item["_category"] = category
                output.append(item)
    return output


async def get_calendrier_club_service(params: CalendrierClubInput) -> list[dict]:
    client = await get_client_async()
    query = params.club_name
    if params.categorie:
        query += f" {params.categorie}"

    results = await _safe_call(
        f"Calendrier club: {query}",
        client.search_rencontres_async(query)
    )
    if not results or not results.hits:
        return []

    flat: list[dict[str, Any]] = []
    for hit in results.hits:
        raw = serialize_model(hit)
        flat.append(
            {
                "id": raw.get("id"),
                "date": raw.get("date_rencontre", raw.get("date")),
                "nom_equipe1": raw.get("nom_equipe1", ""),
                "nom_equipe2": raw.get("nom_equipe2", ""),
                "numero_journee": raw.get("numero_journee"),
                "gs_id": raw.get("gs_id"),
            }
        )
    return flat
