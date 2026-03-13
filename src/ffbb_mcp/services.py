from __future__ import annotations

import asyncio
import logging
import re
import time
import traceback
from threading import RLock
from typing import Any, TypeVar

from cachetools import TTLCache
from ffbb_api_client_v3.config import (
    MEILISEARCH_INDEX_COMPETITIONS,
    MEILISEARCH_INDEX_ORGANISMES,
    MEILISEARCH_INDEX_PRATIQUES,
    MEILISEARCH_INDEX_RENCONTRES,
    MEILISEARCH_INDEX_SALLES,
    MEILISEARCH_INDEX_TERRAINS,
    MEILISEARCH_INDEX_TOURNOIS,
)
from ffbb_api_client_v3.models import MultiSearchQuery
from httpx import HTTPStatusError
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from .aliases import normalize_query
from .client import get_client_async
from .metrics import record_call
from .utils import serialize_model

logger = logging.getLogger("ffbb-mcp")

T = TypeVar("T")

_PRIMARY_MULTI_SEARCH_INDEXES = {
    MEILISEARCH_INDEX_ORGANISMES,
    MEILISEARCH_INDEX_COMPETITIONS,
    MEILISEARCH_INDEX_RENCONTRES,
}

# ---------------------------------------------------------------------------
# Cache service-level (en mémoire, complémentaire au cache SQLite HTTP)
# ---------------------------------------------------------------------------

_cache_lives = TTLCache(maxsize=1, ttl=30)  # 30 s — scores changent chaque possession
_cache_search = TTLCache(maxsize=256, ttl=600)  # 10 min — résultats de recherche
_cache_detail = TTLCache(maxsize=128, ttl=1200)  # 20 min — détails compétitions/clubs
_cache_calendrier = TTLCache(maxsize=64, ttl=300)  # 5 min — calendriers clubs
_cache_lock = RLock()
_inflight_lock: asyncio.Lock = asyncio.Lock()
_inflight_detail: dict[str, asyncio.Task[Any]] = {}


def _cache_get(cache: TTLCache, key: str) -> Any | None:
    """Lecture thread-safe du cache."""
    with _cache_lock:
        return cache.get(key)


def _cache_set(cache: TTLCache, key: str, value: Any) -> None:
    """Écriture thread-safe dans le cache."""
    with _cache_lock:
        cache[key] = value


def _coerce_numeric_id(value: int | str, label: str) -> int:
    """Convertit un identifiant en entier avec message d'erreur explicite."""
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message=(
                    f"{label} invalide: '{value}'. "
                    "Un identifiant numérique est requis."
                ),
            )
        ) from e


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

    if isinstance(e, HTTPStatusError):
        status = e.response.status_code
        if status == 404:
            return McpError(
                error=ErrorData(
                    code=INTERNAL_ERROR,
                    message="Ressource FFBB introuvable (404). Vérifiez l'identifiant.",
                )
            )
        if status in (401, 403):
            return McpError(
                error=ErrorData(
                    code=INTERNAL_ERROR,
                    message="Accès FFBB refusé (401/403). Les tokens sont peut-être expirés.",
                )
            )
        if status == 429:
            return McpError(
                error=ErrorData(
                    code=INTERNAL_ERROR,
                    message="Rate-limit FFBB atteint (429). Réessayez dans quelques secondes.",
                )
            )

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


async def _dedupe_inflight_detail(cache_key: str, make_coro) -> Any:
    """Déduplique les appels concurrents sur la même clé de détail."""
    cached = _cache_get(_cache_detail, cache_key)
    if cached is not None:
        return cached

    async with _inflight_lock:
        existing = _inflight_detail.get(cache_key)
        if existing is not None:
            return await existing

        task = asyncio.create_task(make_coro())
        _inflight_detail[cache_key] = task

    try:
        result = await task
        _cache_set(_cache_detail, cache_key, result)
        return result
    finally:
        async with _inflight_lock:
            _inflight_detail.pop(cache_key, None)


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
    competition_id_int = _coerce_numeric_id(competition_id, "competition_id")
    cache_key = f"competition:{competition_id_int}"

    async def _fetch() -> dict:
        client = await get_client_async()
        comp = await _safe_call(
            f"Compétition {competition_id_int}",
            client.get_competition_async(competition_id=competition_id_int),
        )
        return serialize_model(comp) or {}

    return await _dedupe_inflight_detail(cache_key, _fetch)


async def get_poule_service(poule_id: int | str) -> dict:
    poule_id_int = _coerce_numeric_id(poule_id, "poule_id")
    cache_key = f"poule:{poule_id_int}"

    async def _fetch() -> dict:
        client = await get_client_async()
        poule = await _safe_call(
            f"Poule {poule_id_int}",
            client.get_poule_async(poule_id=poule_id_int),
        )
        return serialize_model(poule) or {}

    return await _dedupe_inflight_detail(cache_key, _fetch)


async def get_organisme_service(organisme_id: int | str) -> dict:
    organisme_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    cache_key = f"organisme:{organisme_id_int}"

    async def _fetch() -> dict:
        client = await get_client_async()
        org = await _safe_call(
            f"Organisme {organisme_id_int}",
            client.get_organisme_async(organisme_id=organisme_id_int),
        )
        return serialize_model(org) or {}

    return await _dedupe_inflight_detail(cache_key, _fetch)


async def ffbb_equipes_club_service(
    organisme_id: int | str, filtre: str | None = None
) -> list[dict[str, Any]]:
    # ✅ Utilise get_organisme_service qui a le TTLCache
    data = await get_organisme_service(organisme_id)
    if not data:
        return []

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
            cat_code_low = (cat.get("code") or "").lower()  # ex: "u13"
            sexe_field = (comp.get("sexe") or "").upper()  # ex: "M" ou "F"

            # 1. Extraction Catégorie (Uxx) du filtre
            cat_match = re.search(r"(u\d+)", f_low)
            if cat_match and cat_match.group(1) != cat_code_low:
                continue

            # 2. Extraction Genre du filtre
            is_f = bool(re.search(r"(?:\bf\b|u\d+f|féminin|feminin|fille)", f_low))
            is_m = bool(re.search(r"(?:\bm\b|u\d+m|masculin|garçon|garcon)", f_low))

            if is_f and sexe_field != "F":
                continue
            if is_m and sexe_field != "M":
                continue

            # 3. Extraction Numéro d'équipe (ex: le 2 dans U13F2 ou U13-2)
            # On cherche un chiffre à la toute fin du filtre, eventuellement précédé d'un espace, tiret, ou lettre
            num_match = re.search(r"(\d)$", f_low.strip())
            # On ignore si c'est juste le chiffre de la catégorie (ex: "U13")
            if num_match and not re.search(r"u\d+$", f_low.strip()):
                target_num = num_match.group(1)
                team_num = str(e.get("numeroEquipe", ""))
                # If team_num is empty, sometimes "1" is implied, but strict matching is safer
                if target_num != team_num and not (target_num == "1" and not team_num):
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
    poule_id_int = _coerce_numeric_id(poule_id, "poule_id")
    cache_key = f"classement:{poule_id_int}"
    cached = _cache_get(_cache_detail, cache_key)
    if cached is not None:
        return cached

    client = await get_client_async()
    poule = await _safe_call(
        f"Classement poule {poule_id_int}",
        client.get_poule_async(poule_id=poule_id_int),
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
    primary_limit = min(limit, max(2, (limit + 2) // 3))
    secondary_limit = min(limit, max(1, (limit + 9) // 10))
    queries = [
        MultiSearchQuery(
            index_uid=MEILISEARCH_INDEX_ORGANISMES,
            q=normalized_query,
            limit=primary_limit,
        ),
        MultiSearchQuery(
            index_uid=MEILISEARCH_INDEX_COMPETITIONS,
            q=normalized_query,
            limit=primary_limit,
        ),
        MultiSearchQuery(
            index_uid=MEILISEARCH_INDEX_RENCONTRES,
            q=normalized_query,
            limit=primary_limit,
        ),
        MultiSearchQuery(
            index_uid=MEILISEARCH_INDEX_SALLES,
            q=normalized_query,
            limit=secondary_limit,
        ),
        MultiSearchQuery(
            index_uid=MEILISEARCH_INDEX_PRATIQUES,
            q=normalized_query,
            limit=secondary_limit,
        ),
        MultiSearchQuery(
            index_uid=MEILISEARCH_INDEX_TERRAINS,
            q=normalized_query,
            limit=secondary_limit,
        ),
        MultiSearchQuery(
            index_uid=MEILISEARCH_INDEX_TOURNOIS,
            q=normalized_query,
            limit=secondary_limit,
        ),
    ]
    raw = await _safe_call(f"Multi-search: {nom}", client.multi_search_async(queries))

    if not raw or not hasattr(raw, "results") or not raw.results:
        return []

    output: list[dict[str, Any]] = []

    for res in raw.results:
        category = res.index_uid
        for hit in res.hits:
            item = serialize_model(hit)
            item["_type"] = category
            output.append(item)
            if len(output) >= limit:
                _cache_set(_cache_search, cache_key, output)
                return output

    _cache_set(_cache_search, cache_key, output)
    return output


async def get_calendrier_club_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
) -> list[dict]:
    """
    Récupère le calendrier et les résultats d'un club en utilisant le workflow infaillible
    (Recherche Club -> Equipes -> Poules -> Rencontres).
    """
    # Clé de cache stable
    cache_key = f"calendrier:{organisme_id or ''}:{(club_name or '').lower().strip()}:{categorie or ''}"
    cached = _cache_get(_cache_calendrier, cache_key)
    if cached is not None:
        logger.debug(f"Cache hit: {cache_key}")
        return cached

    target_org_ids = []

    if organisme_id:
        target_org_ids = [organisme_id]
    elif club_name:
        orgs = await search_organismes_service(nom=club_name, limit=3)
        target_org_ids = [
            org.get("id") for org in orgs if isinstance(org, dict) and org.get("id")
        ]

    target_org_ids = list(dict.fromkeys(str(oid) for oid in target_org_ids))

    if not target_org_ids:
        return []

    # 2. Récupérer les équipes engagées correspondant à la catégorie en parallèle
    eq_tasks = [
        ffbb_equipes_club_service(organisme_id=oid, filtre=categorie)
        for oid in target_org_ids
    ]
    eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

    equipes = []
    for res in eq_results:
        if isinstance(res, list):
            equipes.extend(res)
        elif isinstance(res, Exception):
            logger.error(f"Erreur lors de la récupération des équipes: {res}")

    if not equipes:
        return []

    deduped_equipes: list[dict[str, Any]] = []
    seen_engagement_ids: set[str] = set()
    for equipe in equipes:
        engagement_id = equipe.get("engagement_id")
        if engagement_id is None:
            deduped_equipes.append(equipe)
            continue
        engagement_key = str(engagement_id)
        if engagement_key in seen_engagement_ids:
            continue
        seen_engagement_ids.add(engagement_key)
        deduped_equipes.append(equipe)

    equipes = deduped_equipes

    # 3. Parcourir toutes les poules de ces équipes pour récupérer toutes les rencontres et scores
    seen_match_ids = set()
    all_matches = []

    # Concurrency for massive performance improvements (avoids repeated blocking lookups)
    unique_poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )
    poule_tasks = [get_poule_service(poule_id) for poule_id in unique_poule_ids]
    poules_data = await asyncio.gather(*poule_tasks, return_exceptions=True)
    poules_by_id = {
        poule_id: poule_data
        for poule_id, poule_data in zip(unique_poule_ids, poules_data, strict=False)
    }

    for equipe in equipes:
        poule_id = equipe.get("poule_id")
        if not poule_id:
            continue

        poule_data = poules_by_id.get(str(poule_id))
        if (
            isinstance(poule_data, Exception)
            or not poule_data
            or "rencontres" not in poule_data
        ):
            continue

        for match in poule_data.get("rencontres", []):
            match_id = match.get("id")
            if not match_id or match_id in seen_match_ids:
                continue

            # --- Filtrage robuste : engagement_id OU nom_equipe ---
            eng1 = match.get("idEngagementEquipe1")
            eng2 = match.get("idEngagementEquipe2")
            id_eng1 = eng1.get("id") if isinstance(eng1, dict) else eng1
            id_eng2 = eng2.get("id") if isinstance(eng2, dict) else eng2

            my_eng_id = equipe.get("engagement_id")
            my_team_name = (equipe.get("nom_equipe") or "").lower().strip()

            # Strategy 1: engagement ID matching (precise)
            if my_eng_id and id_eng1 and id_eng2:
                if str(my_eng_id) not in (str(id_eng1), str(id_eng2)):
                    continue
            elif my_team_name:
                # Strategy 2: fall back to team name matching
                eq1_name = (
                    match.get("nomEquipe1") or match.get("nom_equipe1") or ""
                ).lower()
                eq2_name = (
                    match.get("nomEquipe2") or match.get("nom_equipe2") or ""
                ).lower()
                if my_team_name not in eq1_name and my_team_name not in eq2_name:
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
    _cache_set(_cache_calendrier, cache_key, all_matches)
    return all_matches
