import logging
import traceback
from typing import Any, TypeVar

from ffbb_api_client_v3.helpers.multi_search_query_helper import generate_queries
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from .client import get_client_async
from .schemas import SearchInput, CalendrierClubInput
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

from typing import Any, TypeVar, Union, Optional

async def get_lives_service() -> list[dict]:
    client = await get_client_async()
    lives = await _safe_call("Lives (Matchs en cours)", client.get_lives_async())
    if not lives:
        return []
    return [serialize_model(live) for live in lives]


async def get_saisons_service(active_only: bool = False) -> list[dict]:
    client = await get_client_async()
    saisons = await _safe_call(
        "Saisons", 
        client.get_saisons_async(active_only=active_only)
    )
    if not saisons:
        return []
    return [serialize_model(s) for s in saisons]


async def get_competition_service(competition_id: Union[int, str]) -> dict:
    client = await get_client_async()
    comp = await _safe_call(
        f"Compétition {competition_id}",
        client.get_competition_async(competition_id=int(competition_id))
    )
    return serialize_model(comp) or {}


async def get_poule_service(poule_id: Union[int, str]) -> dict:
    client = await get_client_async()
    poule = await _safe_call(
        f"Poule {poule_id}",
        client.get_poule_async(poule_id=int(poule_id))
    )
    return serialize_model(poule) or {}


async def get_organisme_service(organisme_id: Union[int, str]) -> dict:
    client = await get_client_async()
    org = await _safe_call(
        f"Organisme {organisme_id}",
        client.get_organisme_async(organisme_id=int(organisme_id))
    )
    return serialize_model(org) or {}


async def ffbb_equipes_club_service(
    organisme_id: Union[int, str], 
    filtre: Optional[str] = None
) -> list[dict[str, Any]]:
    client = await get_client_async()
    org = await _safe_call(
        f"Equipes club {organisme_id}",
        client.get_organisme_async(organisme_id=int(organisme_id))
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
        nom_comp = comp.get("nom", "")
        
        # Filtre optionnel pour gagner du temps agents
        if filtre and filtre.lower() not in nom_comp.lower():
            continue

        flat.append(
            {
                "engagement_id": e.get("id"),
                "nom_equipe": club_nom,
                "competition": nom_comp,
                "competition_id": comp.get("id"),
                "poule_id": poule.get("id"),
                "sexe": comp.get("sexe", ""),
                "categorie": cat.get("code", ""),
                "niveau": comp.get("competition_origine_niveau"),
            }
        )
    return flat


async def ffbb_get_classement_service(poule_id: Union[int, str]) -> list[dict[str, Any]]:
    client = await get_client_async()
    poule = await _safe_call(
        f"Classement poule {poule_id}",
        client.get_poule_async(poule_id=int(poule_id))
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
                "points": c.get("points"),
                "match_joues": c.get("match_joues"),
                "gagnes": c.get("gagnes"),
                "perdus": c.get("perdus"),
                "difference": c.get("difference"),
            }
        )
    return flat


async def _search_generic(operation: str, method_name: str, query: str) -> list[dict]:
    client = await get_client_async()
    method = getattr(client, method_name)
    results = await _safe_call(f"Recherche {operation}: {query}", method(query))
    if not results or not results.hits:
        return []
    return [serialize_model(hit) for hit in results.hits]


async def search_competitions_service(nom: str) -> list[dict]:
    return await _search_generic("competitions", "search_competitions_async", nom)


async def search_organismes_service(nom: str) -> list[dict]:
    return await _search_generic("organismes", "search_organismes_async", nom)


async def search_salles_service(nom: str) -> list[dict]:
    return await _search_generic("salles", "search_salles_async", nom)


async def search_rencontres_service(nom: str) -> list[dict]:
    return await _search_generic("rencontres", "search_rencontres_async", nom)


async def search_pratiques_service(nom: str) -> list[dict]:
    return await _search_generic("pratiques", "search_pratiques_async", nom)


async def search_terrains_service(nom: str) -> list[dict]:
    return await _search_generic("terrains", "search_terrains_async", nom)


async def search_tournois_service(nom: str) -> list[dict]:
    return await _search_generic("tournois", "search_tournois_async", nom)


async def multi_search_service(nom: str) -> list[dict[str, Any]]:
    client = await get_client_async()
    queries = generate_queries(nom)
    results = await _safe_call(
        f"Recherche multi-types: {nom}",
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
                # Type helper pour aider l'agent à savoir quel outil utiliser ensuite
                item["_type"] = category
                output.append(item)
    return output


async def get_calendrier_club_service(
    club_name: Optional[str] = None, 
    organisme_id: Optional[Union[int, str]] = None,
    categorie: Optional[str] = None
) -> list[dict]:
    client = await get_client_async()
    
    search_term = club_name or ""
    
    # Auto-résolution du nom via ID pour une recherche plus précise
    if organisme_id:
        org = await _safe_call(
            f"Résolution club {organisme_id}",
            client.get_organisme_async(organisme_id=int(organisme_id))
        )
        if org:
            data = serialize_model(org)
            search_term = data.get("nom", search_term)
    
    if not search_term:
        return []
        
    query = search_term
    if categorie:
        query += f" {categorie}"

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
                "equipe1": raw.get("nom_equipe1", ""),
                "equipe2": raw.get("nom_equipe2", ""),
                "num_journee": raw.get("numero_journee"),
            }
        )
    return flat
