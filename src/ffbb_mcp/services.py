from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import traceback
from threading import RLock
from typing import Any, TypeVar

from cachetools import TTLCache

# NOTE: importing ffbb_api_client_v3 at module import time is relatively
# expensive (triggers meilisearch client initialization). We perform
# local/lazy imports in the functions that actually need these symbols
# to reduce cold-start/import overhead.
from httpx import HTTPStatusError
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from .aliases import normalize_query
from .client import get_client_async
from .metrics import record_call
from .utils import serialize_model

logger = logging.getLogger("ffbb-mcp")

T = TypeVar("T")

# Precompile regex used heavily in `ffbb_equipes_club_service` to avoid
# recompiling on every call.
_RE_CAT = re.compile(r"(u\d+)")
_RE_IS_F = re.compile(r"(?:\bf\b|u\d+f|féminin|feminin|fille)")
_RE_IS_M = re.compile(r"(?:\bm\b|u\d+m|masculin|garçon|garcon)")
_RE_NUM_END = re.compile(r"(\d)$")

# ---------------------------------------------------------------------------
# Cache service-level (en mémoire, complémentaire au cache SQLite HTTP)
# ---------------------------------------------------------------------------

_cache_lives = TTLCache(maxsize=1, ttl=30)  # 30 s — scores changent chaque possession
_cache_search = TTLCache(maxsize=256, ttl=600)  # 10 min — résultats de recherche
_cache_detail = TTLCache(maxsize=128, ttl=1200)  # 20 min — détails compétitions/clubs
_cache_calendrier = TTLCache(maxsize=64, ttl=300)  # 5 min — calendriers clubs
_cache_bilan = TTLCache(maxsize=64, ttl=300)  # 5 min — bilans toutes phases
_cache_lock = RLock()
_inflight_lock: asyncio.Lock = asyncio.Lock()
_inflight_detail: dict[str, asyncio.Task[Any]] = {}
_inflight_search: dict[str, asyncio.Task[Any]] = {}
_inflight_calendrier: dict[str, asyncio.Task[Any]] = {}
_inflight_bilan: dict[str, asyncio.Task[Any]] = {}


def _read_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


_MAX_POULE_FETCH_CONCURRENCY = _read_positive_int_env("FFBB_POULE_FETCH_CONCURRENCY", 8)


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
                    f"{label} invalide: '{value}'. Un identifiant numérique est requis."
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
    return await _dedupe_inflight(
        cache=_cache_detail,
        cache_key=cache_key,
        inflight_map=_inflight_detail,
        make_coro=make_coro,
    )


async def _dedupe_inflight(
    *,
    cache: TTLCache | None,
    cache_key: str,
    inflight_map: dict[str, asyncio.Task[Any]],
    make_coro,
) -> Any:
    """Déduplique les appels concurrents sur une clé et met en cache le résultat."""
    if cache is not None:
        cached = _cache_get(cache, cache_key)
        if cached is not None:
            return cached

    existing: asyncio.Task[Any] | None = None
    async with _inflight_lock:
        existing = inflight_map.get(cache_key)
        if existing is None:
            existing = asyncio.create_task(make_coro())
            inflight_map[cache_key] = existing

    try:
        result = await existing
        if cache is not None:
            _cache_set(cache, cache_key, result)
        return result
    finally:
        async with _inflight_lock:
            inflight_map.pop(cache_key, None)


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
    organisme_id: int | str | None = None,
    filtre: str | None = None,
    org_data: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Retourne les équipes engagées pour un club.

    Paramètre `org_data` optionnel : si fourni, évite un appel supplémentaire
    à `get_organisme_service` (utile quand l'appelant a déjà chargé l'organisme).
    """
    # Réutilise org_data si fourni, sinon récupère via get_organisme_service
    data = (
        org_data if org_data is not None else await get_organisme_service(organisme_id)
    )
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
            cat_code_low = (cat.get("code") or "").lower()
            sexe_field = (comp.get("sexe") or "").upper()

            # 1. Extraction Catégorie (Uxx) du filtre
            cat_match = _RE_CAT.search(f_low)
            if cat_match and cat_match.group(1) != cat_code_low:
                continue

            # 2. Extraction Genre du filtre (précompilé)
            is_f = bool(_RE_IS_F.search(f_low))
            is_m = bool(_RE_IS_M.search(f_low))

            if is_f and sexe_field != "F":
                continue
            if is_m and sexe_field != "M":
                continue

            # 3. Extraction Numéro d'équipe (ex: le 2 dans U13F2 ou U13-2)
            num_match = _RE_NUM_END.search(f_low.strip())
            if num_match and not re.search(r"u\d+$", f_low.strip()):
                target_num = num_match.group(1)
                team_num = str(e.get("numeroEquipe", ""))
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

    async def _fetch() -> list[dict]:
        # Lazy import to avoid heavy ffbb_api_client_v3 initialization at
        # module import time.

        client = await get_client_async()
        method = getattr(client, method_name)
        results = await _safe_call(
            f"Search {operation}: {query}", method(normalized_query)
        )
        if not results or not results.hits:
            return []
        return [serialize_model(hit) for hit in results.hits[:limit]]

    return await _dedupe_inflight(
        cache=_cache_search,
        cache_key=cache_key,
        inflight_map=_inflight_search,
        make_coro=_fetch,
    )


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

    async def _fetch() -> list[dict[str, Any]]:
        # Lazy imports to avoid heavy ffbb_api_client_v3 initialization at
        # module import time.
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

        raw = await _safe_call(
            f"Multi-search: {nom}", client.multi_search_async(queries)
        )

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
                    return output
        return output

    return await _dedupe_inflight(
        cache=_cache_search,
        cache_key=cache_key,
        inflight_map=_inflight_search,
        make_coro=_fetch,
    )


async def ffbb_bilan_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
) -> dict[str, Any]:
    """
    Bilan complet d'une équipe toutes phases confondues en un seul appel.
    Workflow interne : search → equipes → poules (parallèle) → agrégation V/D/N + paniers.
    """
    cache_key = f"bilan:{organisme_id or ''}:{(club_name or '').lower().strip()}:{categorie or ''}"

    async def _fetch() -> dict[str, Any]:
        # 1. Résoudre l'organisme_id
        target_org_ids: list[str] = []
        club_nom = club_name or ""

        # FIX: org_data initialisé à None avant le try pour éviter un NameError
        # si get_organisme_service lève une exception.
        org_data: dict | None = None

        if organisme_id:
            target_org_ids = [str(organisme_id)]
            try:
                org_data = await get_organisme_service(organisme_id)
                if isinstance(org_data, dict) and org_data.get("nom"):
                    club_nom = org_data.get("nom")
            except Exception:
                pass
        elif club_name:
            orgs = await search_organismes_service(nom=club_name, limit=5)
            target_org_ids = [
                str(org["id"])
                for org in orgs
                if isinstance(org, dict) and org.get("id")
            ]
            if orgs and isinstance(orgs[0], dict):
                club_nom = orgs[0].get("nom", club_name) or club_name or ""

        if not target_org_ids:
            return {"error": f"Club '{club_name}' introuvable"}

        # 2. Récupérer les équipes filtrées en parallèle
        eq_tasks = []
        for oid in target_org_ids:
            if (
                organisme_id
                and str(oid) == str(organisme_id)
                and isinstance(org_data, dict)
            ):
                eq_tasks.append(
                    ffbb_equipes_club_service(
                        organisme_id=oid, filtre=categorie, org_data=org_data
                    )
                )
            else:
                eq_tasks.append(
                    ffbb_equipes_club_service(organisme_id=oid, filtre=categorie)
                )
        eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

        equipes: list[dict[str, Any]] = []
        for res in eq_results:
            if isinstance(res, list):
                equipes.extend(res)

        if not equipes:
            return {"error": f"Aucune équipe trouvée pour la catégorie '{categorie}'"}

        # Dédupliquer par engagement_id
        seen_eng: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for e in equipes:
            key = str(e.get("engagement_id", ""))
            if key not in seen_eng:
                seen_eng.add(key)
                deduped.append(e)
        equipes = deduped

        # 3. Récupérer toutes les poules en parallèle
        unique_poule_ids = list(
            dict.fromkeys(str(e["poule_id"]) for e in equipes if e.get("poule_id"))
        )
        # FIX: print() → logger.debug() (les print polluaient stdout/Coolify en prod)
        logger.debug(f"ffbb_bilan: club_nom={club_nom} cible_orgs={target_org_ids}")
        logger.debug(
            f"ffbb_bilan: equipes_count={len(equipes)} unique_poules={unique_poule_ids}"
        )

        semaphore = asyncio.Semaphore(_MAX_POULE_FETCH_CONCURRENCY)

        async def _fetch_poule_bilan(pid: str) -> dict[str, Any] | Exception:
            async with semaphore:
                try:
                    return await get_poule_service(pid)
                except McpError:
                    try:
                        client = await get_client_async()
                        poule = await _safe_call(
                            f"Poule {pid}", client.get_poule_async(poule_id=pid)
                        )
                        return serialize_model(poule) or {}
                    except Exception as e:
                        return e

        poules_raw = await asyncio.gather(
            *[_fetch_poule_bilan(pid) for pid in unique_poule_ids],
            return_exceptions=True,
        )
        logger.debug("ffbb_bilan: poules_raw=%s", poules_raw)
        poules_map: dict[str, dict[str, Any]] = {
            pid: pd
            for pid, pd in zip(unique_poule_ids, poules_raw, strict=False)
            if not isinstance(pd, Exception) and pd
        }
        logger.debug("ffbb_bilan: poules_map_keys=%s", list(poules_map.keys()))

        # Map poule_id → engagement_ids du club + nom compétition
        poule_to_eng: dict[str, set[str]] = {}
        poule_to_comp: dict[str, str] = {}
        org_ids_str = set(target_org_ids)
        for e in equipes:
            pid = str(e.get("poule_id", ""))
            eid = str(e.get("engagement_id", ""))
            if pid and eid:
                poule_to_eng.setdefault(pid, set()).add(eid)
            if pid and e.get("competition"):
                poule_to_comp[pid] = e["competition"]

        # 4. Agréger par phase
        phases: list[dict[str, Any]] = []
        totaux: dict[str, int] = {
            "match_joues": 0,
            "gagnes": 0,
            "perdus": 0,
            "nuls": 0,
            "paniers_marques": 0,
            "paniers_encaisses": 0,
            "difference": 0,
        }

        for pid, poule_data in poules_map.items():
            eng_ids_here = poule_to_eng.get(pid, set())
            for entry in poule_data.get("classements", []):
                eng = entry.get("id_engagement", {}) or {}
                entry_eng_id = str(eng.get("id", ""))
                entry_org_id = str(entry.get("organisme_id", ""))

                if entry_eng_id not in eng_ids_here and entry_org_id not in org_ids_str:
                    continue

                mj = int(entry.get("match_joues") or 0)
                g = int(entry.get("gagnes") or 0)
                d = int(entry.get("perdus") or 0)
                n = int(entry.get("nuls") or 0)
                pm = int(entry.get("paniers_marques") or 0)
                pe = int(entry.get("paniers_encaisses") or 0)
                diff = int(entry.get("difference") or 0)

                phases.append(
                    {
                        "competition": poule_to_comp.get(pid, ""),
                        "poule_id": pid,
                        "position": entry.get("position"),
                        "match_joues": mj,
                        "gagnes": g,
                        "perdus": d,
                        "nuls": n,
                        "paniers_marques": pm,
                        "paniers_encaisses": pe,
                        "difference": diff,
                    }
                )

                totaux["match_joues"] += mj
                totaux["gagnes"] += g
                totaux["perdus"] += d
                totaux["nuls"] += n
                totaux["paniers_marques"] += pm
                totaux["paniers_encaisses"] += pe
                totaux["difference"] += diff

        phases.sort(key=lambda x: x["competition"])

        return {
            "club": club_nom,
            "categorie": categorie or "",
            "bilan_total": totaux,
            "phases": phases,
        }

    return await _dedupe_inflight(
        cache=_cache_bilan,
        cache_key=cache_key,
        inflight_map=_inflight_bilan,
        make_coro=_fetch,
    )


async def get_calendrier_club_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
) -> list[dict]:
    """
    Récupère le calendrier et les résultats d'un club en utilisant le workflow infaillible
    (Recherche Club -> Equipes -> Poules -> Rencontres).
    """
    cache_key = f"calendrier:{organisme_id or ''}:{(club_name or '').lower().strip()}:{categorie or ''}"

    async def _fetch() -> list[dict]:

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
        # FIX: org_data supprimée (fetché mais jamais utilisée — appel API gaspillé)
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

        unique_poule_ids = list(
            dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
        )

        semaphore = asyncio.Semaphore(_MAX_POULE_FETCH_CONCURRENCY)

        async def _fetch_poule(poule_id: str) -> dict[str, Any] | Exception:
            async with semaphore:
                return await get_poule_service(poule_id)

        poule_tasks = [_fetch_poule(poule_id) for poule_id in unique_poule_ids]
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

    return await _dedupe_inflight(
        cache=_cache_calendrier,
        cache_key=cache_key,
        inflight_map=_inflight_calendrier,
        make_coro=_fetch,
    )
