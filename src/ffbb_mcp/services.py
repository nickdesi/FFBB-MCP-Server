import logging
import time
import traceback
from typing import Any, TypeVar

from cachetools import TTLCache
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from .aliases import normalize_query
from .client import get_client_async
from .metrics import record_call
from .utils import serialize_model

logger = logging.getLogger("ffbb-mcp")

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Cache service-level (en mémoire, complémentaire au cache SQLite HTTP)
# ---------------------------------------------------------------------------

_cache_lives = TTLCache(maxsize=1, ttl=30)  # 30 s — scores changent chaque possession
_cache_search = TTLCache(maxsize=256, ttl=120)  # 2 min — résultats de recherche
_cache_detail = TTLCache(maxsize=128, ttl=300)  # 5 min — détails compétitions/clubs


def _cache_get(cache: TTLCache, key: str) -> Any | None:
    """Lecture thread-safe du cache."""
    return cache.get(key)


def _cache_set(cache: TTLCache, key: str, value: Any) -> None:
    """Écriture thread-safe dans le cache."""
    cache[key] = value


# ---------------------------------------------------------------------------
# Gestion d'erreurs
# ---------------------------------------------------------------------------


def _handle_api_error(e: Exception) -> McpError:
    """Formatage cohérent des erreurs API pour tous les outils."""
    if isinstance(e, McpError):
        return e

    error_msg = str(e)
    logger.error(f"FFBB API Error: {error_msg}")
    logger.error(traceback.format_exc())

    # Distinguer les timeouts des autres erreurs
    error_type = type(e).__name__
    if "timeout" in error_type.lower() or "timeout" in error_msg.lower():
        return McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message="Timeout API FFBB. L'API officielle est temporairement lente. Réessayez dans quelques secondes.",
            )
        )

    return McpError(
        error=ErrorData(
            code=INTERNAL_ERROR,
            message=f"Erreur API FFBB ({error_type}): {error_msg}",
        )
    )


async def _safe_call(operation_name: str, coro) -> Any:
    """Exécute un appel API avec logging et error handling."""
    logger.info(f"Début exécution: {operation_name}")
    start_time = time.monotonic()
    is_error = False
    try:
        result = await coro
        logger.info(f"Succès: {operation_name}")
        return result
    except Exception as e:
        is_error = True
        raise _handle_api_error(e) from e
    finally:
        latency = time.monotonic() - start_time
        record_call(latency, is_error)


# ---------------------------------------------------------------------------
# Services -- Données en direct
# ---------------------------------------------------------------------------


async def get_lives_service() -> list[dict]:
    cached = _cache_get(_cache_lives, "lives")
    if cached is not None:
        logger.debug("Cache hit: lives")
        return cached

    client = await get_client_async()
    lives = await _safe_call("Lives (Matchs en cours)", client.get_lives_async())
    result = [serialize_model(live) for live in lives] if lives else []
    _cache_set(_cache_lives, "lives", result)
    return result


async def get_saisons_service(active_only: bool = False) -> list[dict]:
    cache_key = f"saisons:{active_only}"
    cached = _cache_get(_cache_detail, cache_key)
    if cached is not None:
        return cached

    client = await get_client_async()
    saisons = await _safe_call(
        "Saisons", client.get_saisons_async(active_only=active_only)
    )
    result = [serialize_model(s) for s in saisons] if saisons else []
    _cache_set(_cache_detail, cache_key, result)
    return result


async def get_competition_service(competition_id: int | str) -> dict:
    cache_key = f"competition:{competition_id}"
    cached = _cache_get(_cache_detail, cache_key)
    if cached is not None:
        return cached

    client = await get_client_async()
    comp = await _safe_call(
        f"Compétition {competition_id}",
        client.get_competition_async(competition_id=int(competition_id)),
    )
    result = serialize_model(comp) or {}
    _cache_set(_cache_detail, cache_key, result)
    return result


async def get_poule_service(poule_id: int | str) -> dict:
    cache_key = f"poule:{poule_id}"
    cached = _cache_get(_cache_detail, cache_key)
    if cached is not None:
        return cached

    client = await get_client_async()
    poule = await _safe_call(
        f"Poule {poule_id}", client.get_poule_async(poule_id=int(poule_id))
    )
    result = serialize_model(poule) or {}
    _cache_set(_cache_detail, cache_key, result)
    return result


async def get_organisme_service(organisme_id: int | str) -> dict:
    cache_key = f"organisme:{organisme_id}"
    cached = _cache_get(_cache_detail, cache_key)
    if cached is not None:
        return cached

    client = await get_client_async()
    org = await _safe_call(
        f"Organisme {organisme_id}",
        client.get_organisme_async(organisme_id=int(organisme_id)),
    )
    result = serialize_model(org) or {}
    _cache_set(_cache_detail, cache_key, result)
    return result


async def ffbb_equipes_club_service(
    organisme_id: int | str, filtre: str | None = None
) -> list[dict[str, Any]]:
    client = await get_client_async()
    org = await _safe_call(
        f"Equipes club {organisme_id}",
        client.get_organisme_async(organisme_id=int(organisme_id)),
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
        if filtre:
            f_low = filtre.lower()
            corpus = f"{nom_comp} {cat.get('code', '')} {comp.get('sexe', '')}".lower()
            # Transformation des classiques (ex: Masculin/M, Féminin/F)
            corpus = corpus.replace("masculin", "m").replace("féminin", "f").replace("feminin", "f")
            f_norm = f_low.replace("masculin", "m").replace("féminin", "f").replace("feminin", "f")
            
            # Simple check
            if f_norm not in corpus:
                # Heuristiques pour "u13m" -> "u13" + "m"
                if len(f_norm) >= 4 and f_norm.startswith("u"):
                    cat_part = f_norm[:3]
                    sexe_part = f_norm[3:]
                    if cat_part not in corpus or sexe_part not in corpus:
                        continue
                else:
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


async def ffbb_get_classement_service(poule_id: int | str) -> list[dict[str, Any]]:
    cache_key = f"classement:{poule_id}"
    cached = _cache_get(_cache_detail, cache_key)
    if cached is not None:
        return cached

    client = await get_client_async()
    poule = await _safe_call(
        f"Classement poule {poule_id}", client.get_poule_async(poule_id=int(poule_id))
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
    _cache_set(_cache_detail, cache_key, flat)
    return flat


async def _search_generic(
    operation: str, method_name: str, query: str, limit: int = 20
) -> list[dict]:
    normalized_query = normalize_query(query)
    cache_key = f"search:{operation}:{normalized_query}:{limit}"
    cached = _cache_get(_cache_search, cache_key)
    if cached is not None:
        logger.debug(f"Cache hit: {cache_key}")
        return cached

    client = await get_client_async()
    method = getattr(client, method_name)
    results = await _safe_call(f"Search {operation}: {query}", method(normalized_query))
    if not results or not results.hits:
        return []
    result = [serialize_model(hit) for hit in results.hits[:limit]]
    _cache_set(_cache_search, cache_key, result)
    return result


async def search_competitions_service(nom: str, limit: int = 20) -> list[dict]:
    return await _search_generic(
        "competitions", "search_competitions_async", nom, limit
    )


async def search_organismes_service(nom: str, limit: int = 20) -> list[dict]:
    return await _search_generic("organismes", "search_organismes_async", nom, limit)


async def search_salles_service(nom: str, limit: int = 20) -> list[dict]:
    return await _search_generic("salles", "search_salles_async", nom, limit)


async def search_rencontres_service(nom: str, limit: int = 20) -> list[dict]:
    return await _search_generic("rencontres", "search_rencontres_async", nom, limit)


async def search_pratiques_service(nom: str, limit: int = 20) -> list[dict]:
    return await _search_generic("pratiques", "search_pratiques_async", nom, limit)


async def search_terrains_service(nom: str, limit: int = 20) -> list[dict]:
    return await _search_generic("terrains", "search_terrains_async", nom, limit)


async def search_tournois_service(nom: str, limit: int = 20) -> list[dict]:
    return await _search_generic("tournois", "search_tournois_async", nom, limit)


async def multi_search_service(nom: str, limit: int = 20) -> list[dict[str, Any]]:
    normalized_query = normalize_query(nom)
    cache_key = f"multi_search:{normalized_query}:{limit}"
    cached = _cache_get(_cache_search, cache_key)
    if cached is not None:
        return cached

    client = await get_client_async()
    raw = await _safe_call(
        f"Multi-search: {nom}", client.get_recherche_multicritere_async(normalized_query)
    )

    if not raw:
        return []

    data = serialize_model(raw)
    output: list[dict[str, Any]] = []

    for category, results in data.items():
        if isinstance(results, dict) and "hits" in results:
            for hit in results["hits"]:
                item = serialize_model(hit)
                # Type helper pour aider l'agent à savoir quel outil utiliser ensuite
                item["_type"] = category
                output.append(item)
    output = output[:limit]
    _cache_set(_cache_search, cache_key, output)
    return output


async def get_calendrier_club_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
) -> list[dict]:
    """
    Récupère le calendrier et les résultats d'un club en utilisant le workflow infaillible
    (Recherche Club -> Equipes -> Poules -> Rencontres), afin de contourner
    les limitations d'indexation de Meilisearch sur les rencontres.
    """
    target_org_id = organisme_id

    # 1. Résoudre le club si on n'a que le nom
    if not target_org_id and club_name:
        orgs = await search_organismes_service(nom=club_name, limit=1)
        if orgs:
            target_org_id = orgs[0].get("id")

    if not target_org_id:
        return []

    # 2. Récupérer les équipes engagées correspondant à la catégorie
    equipes = await ffbb_equipes_club_service(
        organisme_id=target_org_id, filtre=categorie
    )
    if not equipes:
        return []

    # 3. Parcourir toutes les poules de ces équipes pour récupérer toutes les rencontres et scores
    seen_match_ids = set()
    all_matches = []

    # Concurrency for massive performance improvements (avoids 10x 1s blocking lookups)
    import asyncio
    poule_tasks = [get_poule_service(e.get("poule_id")) for e in equipes if e.get("poule_id")]
    poules_data = await asyncio.gather(*poule_tasks, return_exceptions=True)

    for equipe, poule_data in zip(equipes, poules_data, strict=False):
        if isinstance(poule_data, Exception) or not poule_data or "rencontres" not in poule_data:
            continue

        for match in poule_data.get("rencontres", []):
            match_id = match.get("id")
            if not match_id or match_id in seen_match_ids:
                continue

            seen_match_ids.add(match_id)

            # Extraction robuste des champs camelCase (API originelle) ou snake_case
            eq1 = match.get("nomEquipe1", match.get("nom_equipe1", ""))
            eq2 = match.get("nomEquipe2", match.get("nom_equipe2", ""))
            score1 = match.get("resultatEquipe1", match.get("resultat_equipe1"))
            score2 = match.get("resultatEquipe2", match.get("resultat_equipe2"))
            date_match = match.get("date_rencontre", match.get("date", ""))
            journee = match.get("numeroJournee", match.get("numero_journee", ""))

            all_matches.append(
                {
                    "id": match_id,
                    "date": date_match,
                    "equipe1": eq1,
                    "equipe2": eq2,
                    "score_equipe1": score1,
                    "score_equipe2": score2,
                    "competition_nom": equipe.get("competition", ""),
                    "num_journee": journee,
                }
            )

    # Tri par date décroissante pour avoir les derniers matchs en premier
    all_matches.sort(key=lambda x: x.get("date") or "", reverse=True)
    return all_matches
