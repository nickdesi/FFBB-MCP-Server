from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import traceback
from datetime import datetime
from threading import RLock
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from cachetools import TTLCache
from httpx import HTTPStatusError
from mcp.shared.exceptions import ErrorData, McpError
from mcp.types import INTERNAL_ERROR

from .aliases import normalize_query
from .client import get_client_async
from .metrics import dec_inflight, inc_inflight, record_cache_hit, record_cache_miss
from .utils import ParsedCategorie, parse_categorie, serialize_model

logger = logging.getLogger("ffbb-mcp")

T = TypeVar("T")


def _read_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


# Limiter globalement le nombre d'appels concurrents vers l'API FFBB.
# Valeur par défaut prudente, surchargable via l'env MAX_CONCURRENT_FFBB.
_MAX_CONCURRENT_FFBB = int(os.getenv("MAX_CONCURRENT_FFBB", "8"))
_ffbb_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FFBB)

# Hooks simples pour les metrics de cache. Ils sont no-op par défaut et peuvent
# être surchargés depuis metrics.py via une fonction d'initialisation.
_cache_hit_hook: callable | None = record_cache_hit
_cache_miss_hook: callable | None = record_cache_miss


def set_cache_metrics_hooks(
    *, on_hit: callable | None, on_miss: callable | None
) -> None:
    """Configure les callbacks utilisés pour tracer hits/miss des caches.

    Cette fonction reste exposée pour compatibilité, mais par défaut on utilise
    record_cache_hit/record_cache_miss de metrics.py.
    """

    global _cache_hit_hook, _cache_miss_hook
    _cache_hit_hook = on_hit or record_cache_hit
    _cache_miss_hook = on_miss or record_cache_miss


def _notify_cache_hit(cache_name: str) -> None:
    if _cache_hit_hook is not None:
        try:
            _cache_hit_hook(cache_name)
        except Exception:  # sécurité: jamais d'exception dans un hook de métriques
            logger.debug("cache hit hook failed", exc_info=True)


def _notify_cache_miss(cache_name: str) -> None:
    if _cache_miss_hook is not None:
        try:
            _cache_miss_hook(cache_name)
        except Exception:  # idem
            logger.debug("cache miss hook failed", exc_info=True)


# Precompile regex used heavily in `ffbb_equipes_club_service` to avoid
# recompiling on every call.
_RE_CAT = re.compile(r"(u\d+)")
_RE_IS_F = re.compile(r"(?:\bf\b|u\d+f|féminin|feminin|fille)")
_RE_IS_M = re.compile(r"(?:\bm\b|u\d+m|masculin|garçon|garcon)")
_RE_NUM_END = re.compile(r"(\d)$")

# ---------------------------------------------------------------------------
# Cache service-level (en mémoire, complémentaire au cache SQLite HTTP)
# ---------------------------------------------------------------------------

# TTL configurables via variables d'environnement pour affiner par type de données.
# Données très dynamiques (poules/classements/calendriers) doivent être rafraîchies
# très fréquemment, surtout les jours de match.
_LIVES_TTL = _read_positive_int_env("FFBB_CACHE_TTL_LIVES", 30)
_SEARCH_TTL = _read_positive_int_env("FFBB_CACHE_TTL_SEARCH", 600)
_DETAIL_TTL = _read_positive_int_env("FFBB_CACHE_TTL_DETAIL", 43200)  # 12h par défaut
_CALENDRIER_TTL = _read_positive_int_env("FFBB_CACHE_TTL_CALENDRIER", 120)
_BILAN_TTL = _read_positive_int_env("FFBB_CACHE_TTL_BILAN", 300)
# TTL spécifique ultra-court pour les poules (scores + rencontres).
_POULE_TTL = _read_positive_int_env("FFBB_CACHE_TTL_POULE", 120)

_cache_lives = TTLCache(maxsize=1, ttl=_LIVES_TTL)
_cache_search = TTLCache(maxsize=256, ttl=_SEARCH_TTL)
# Cache de détail générique (organismes, saisons, compétitions, poules/classements si non surchargés)
_cache_detail = TTLCache(maxsize=128, ttl=_DETAIL_TTL)
_cache_calendrier = TTLCache(maxsize=64, ttl=_CALENDRIER_TTL)
_cache_bilan = TTLCache(maxsize=64, ttl=_BILAN_TTL)
_cache_lock = RLock()
_inflight_lock: asyncio.Lock = asyncio.Lock()
_inflight_detail: dict[str, asyncio.Task[Any]] = {}
_inflight_search: dict[str, asyncio.Task[Any]] = {}
_inflight_calendrier: dict[str, asyncio.Task[Any]] = {}
_inflight_bilan: dict[str, asyncio.Task[Any]] = {}


def get_cache_ttls() -> dict[str, int]:
    """Retourne les TTL (en secondes) pour chaque cache service-level.

    Cette fonction fournit une vue compacte et strictement typée des TTL,
    utilisable par un outil de version/status sans exposer les objets TTLCache.
    """

    return {
        "lives": int(_cache_lives.ttl),
        "search": int(_cache_search.ttl),
        "detail": int(_cache_detail.ttl),
        "calendrier": int(_cache_calendrier.ttl),
        "bilan": int(_cache_bilan.ttl),
        "poule": _POULE_TTL,
    }


_MAX_POULE_FETCH_CONCURRENCY = _read_positive_int_env("FFBB_POULE_FETCH_CONCURRENCY", 8)


async def _with_ffbb_semaphore(coro):
    """Helper pour exécuter un appel réseau FFBB sous le sémaphore global.

    Cela encapsule la contrainte de concurrence en un seul endroit, ce qui rend
    plus simple l'utilisation dans les différents services.
    """

    async with _ffbb_semaphore:
        return await coro


def _cache_get(cache: TTLCache, key: Any, cache_name: str) -> Any | None:
    """Wrapper centralisé pour lire un cache avec metrics hit/miss.

    Ce helper évite de dupliquer la logique de notification et permet de
    garder une sémantique uniforme sur tous les caches du module.
    """

    value = cache.get(key)
    if value is not None:
        _notify_cache_hit(cache_name)
    else:
        _notify_cache_miss(cache_name)
    return value


def _cache_set(cache: TTLCache, key: Any, value: Any, cache_name: str) -> None:
    cache[key] = value
    # Le miss correspondant a déjà été enregistré dans _cache_get.


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


async def _safe_call(
    operation_name: str,
    coro,
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
) -> Any:
    """Exécute un appel API avec logging, error handling et retry/backoff.

    `coro` peut être soit une coroutine (non-réessayable), soit un "callable"
    zéro-argument qui retourne une nouvelle coroutine (réessayable).
    """
    logger.info(f"Début exécution: {operation_name}")

    # If a factory is provided, use it to create fresh coroutines per attempt.
    make_coro = None
    if callable(coro):
        make_coro = coro
    else:
        # single-use coroutine passed; wrap into a factory that returns it once
        single = coro

        def _once():
            return single

        make_coro = _once

    attempt = 0
    last_exc: Exception | None = None
    while attempt < max(1, retries):
        attempt += 1
        try:
            current_coro = make_coro()
            result = await current_coro
            logger.info(f"Succès: {operation_name} (attempt {attempt})")
            return result
        except Exception as e:
            last_exc = e

            # Decide if error is retriable
            retriable = False
            if isinstance(e, HTTPStatusError):
                status = getattr(e.response, "status_code", None)
                if status == 429:
                    retriable = True
            errname = type(e).__name__.lower()
            msg = str(e).lower()
            if "timeout" in errname or "timeout" in msg or "connection" in msg:
                retriable = True

            if attempt >= retries or not retriable:
                # no more retries or not retriable: raise handled error
                raise _handle_api_error(e) from e

            # exponential backoff with jitter
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jitter = random.random() * (delay * 0.1)
            sleep_for = delay + jitter
            logger.warning(
                "%s failed (attempt %d/%d) — retrying in %.2fs: %s",
                operation_name,
                attempt,
                retries,
                sleep_for,
                e,
            )
            try:
                await asyncio.sleep(sleep_for)
            except asyncio.CancelledError:
                raise
    # If we exit loop without returning, raise last exception formatted
    if last_exc is not None:
        raise _handle_api_error(last_exc) from last_exc
    return None


async def _safe_call_with_inflight(
    operation_name: str,
    coro_factory,
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
) -> Any:
    """Wrapper autour de _safe_call qui incrémente/décrémente le compteur inflight.

    Utilisé pour exposer une métrique ffbb_api_inflight_requests.
    """

    inc_inflight()
    try:
        return await _safe_call(
            operation_name,
            coro_factory,
            retries=retries,
            base_delay=base_delay,
            max_delay=max_delay,
        )
    finally:
        dec_inflight()


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
        cached = _cache_get(cache, cache_key, "detail")
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
            _cache_set(cache, cache_key, result, "detail")
        return result
    finally:
        async with _inflight_lock:
            inflight_map.pop(cache_key, None)


# ---------------------------------------------------------------------------
# Services -- Données en direct
# ---------------------------------------------------------------------------


async def get_lives_service() -> list[dict]:
    cached = _cache_get(_cache_lives, "lives", "lives")
    if cached is not None:
        logger.debug("Cache hit: lives")
        return cached

    client = await get_client_async()
    lives = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            "Lives (Matchs en cours)", lambda: client.get_lives_async()
        )
    )
    result = [serialize_model(live) for live in lives] if lives else []
    _cache_set(_cache_lives, "lives", result, "lives")
    return result


async def get_saisons_service(active_only: bool = False) -> list[dict]:
    cache_key = f"saisons:{active_only}"
    cached = _cache_get(_cache_detail, cache_key, "saisons")
    if cached is not None:
        return cached

    client = await get_client_async()
    saisons = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            "Saisons", lambda: client.get_saisons_async(active_only=active_only)
        )
    )
    result = [serialize_model(s) for s in saisons] if saisons else []
    _cache_set(_cache_detail, cache_key, result, "saisons")
    return result


async def get_competition_service(competition_id: int | str) -> dict:
    competition_id_int = _coerce_numeric_id(competition_id, "competition_id")
    cache_key = f"competition:{competition_id_int}"

    async def _fetch() -> dict:
        client = await get_client_async()
        comp = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Competition {competition_id_int}",
                lambda: client.get_competition_async(competition_id=competition_id_int),
            ),
        )
        return serialize_model(comp) or {}

    return await _dedupe_inflight_detail(cache_key, _fetch)


async def get_poule_service(poule_id: int | str, *, force_refresh: bool = False) -> dict:
    poule_id_int = _coerce_numeric_id(poule_id, "poule_id")
    cache_key = f"poule:{poule_id_int}"

    async def _fetch() -> dict:
        client = await get_client_async()
        poule = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Poule {poule_id_int}",
                lambda: client.get_poule_async(poule_id=poule_id_int),
            ),
        )
        data = serialize_model(poule) or {}
        # On met à jour explicitement un cache dédié très court pour les poules.
        _cache_set(_cache_detail, cache_key, data, "poule")
        return data

    # force_refresh=True contourne le cache et écrase la valeur précédente.
    if force_refresh:
        return await _fetch()

    # Lecture du cache avant de dédupliquer les appels concurrents.
    cached = _cache_get(_cache_detail, cache_key, "poule")
    if cached is not None:
        return cached

    # On utilise toujours le mécanisme de déduplication pour éviter de frapper
    # l'API FFBB plusieurs fois pour la même poule en parallèle.
    return await _dedupe_inflight_detail(cache_key, _fetch)


async def get_organisme_service(organisme_id: int | str) -> dict:
    organisme_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    cache_key = f"organisme:{organisme_id_int}"

    async def _fetch() -> dict:
        client = await get_client_async()
        org = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Organisme {organisme_id_int}",
                lambda: client.get_organisme_async(organisme_id=organisme_id_int),
            ),
        )
        return serialize_model(org) or {}

    return await _dedupe_inflight_detail(cache_key, _fetch)


async def ffbb_get_classement_service(
    poule_id: int | str,
    *,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    poule_id_int = _coerce_numeric_id(poule_id, "poule_id")
    cache_key = f"classement:{poule_id_int}"

    if not force_refresh:
        cached = _cache_get(_cache_detail, cache_key, "classement")
        if cached is not None:
            return cached

    client = await get_client_async()
    poule = await _with_ffbb_semaphore(
        _safe_call(
            f"Classement poule {poule_id_int}",
            lambda: client.get_poule_async(poule_id=poule_id_int),
        )
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
    _cache_set(_cache_detail, cache_key, flat, "classement")
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
        results = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Search {operation}: {query}", lambda: method(normalized_query)
            )
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

        raw = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Multi-search: {nom}", lambda: client.multi_search_async(queries)
            )
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


async def ffbb_equipes_club_service(
    organisme_id: int | str | None = None,
    filtre: str | None = None,
    org_data: dict | None = None,
) -> list[dict[str, Any]]:
    """Retourne les équipes engagées pour un club.

    Paramètre `org_data` optionnel : si fourni, évite un appel supplémentaire
    à `get_organisme_service` (utile quand l'appelant a déjà chargé l'organisme).

    Cette version expose explicitement :
      - `numero_equipe` : numéro d'équipe dans la catégorie ("1", "2", ...),
      - `team_id` / `engagement_id` : identifiant stable de l'engagement,
      - `team_label` : libellé directement exploitable par un agent (ex: "U11M1").

    Ces champs permettent aux agents IA de désambiguïser rapidement les équipes
    sans devoir inspecter les poules une par une.
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

    parsed_filter: ParsedCategorie | None = parse_categorie(filtre) if filtre else None

    for e in raw:
        comp = e.get("idCompetition", {}) or {}
        poule = e.get("idPoule", {}) or {}
        cat = comp.get("categorie", {}) or {}
        nom_comp = comp.get("nom", "")
        sexe_field = (comp.get("sexe") or "").upper()

        # Filtre optionnel :
        # - on applique toujours le filtre sur le code de catégorie (strict)
        # - on n’exclut sur le sexe / numero_equipe que lorsqu’une information explicite
        #   est disponible côté FFBB. En absence de champ, on laisse passer le candidat,
        #   et la désambiguïsation fine est gérée plus haut (ffbb_resolve_team_service).
        if parsed_filter is not None:
            cat_code = (cat.get("code") or "").upper()
            if parsed_filter.categorie and cat_code != parsed_filter.categorie:
                continue

            if parsed_filter.sexe == "F" and sexe_field == "M":
                continue
            if parsed_filter.sexe == "M" and sexe_field == "F":
                continue

            if parsed_filter.numero_equipe is not None:
                team_num_raw = e.get("numeroEquipe")
                team_num: int | None
                try:
                    team_num = int(team_num_raw) if team_num_raw is not None else None
                except (TypeError, ValueError):
                    team_num = None

                # Si l’API FFBB expose un numeroEquipe explicite différent du filtre,
                # on exclut. Sinon (numeroEquipe manquant ou égal), on garde.
                if team_num is not None and team_num != parsed_filter.numero_equipe:
                    continue

        # Enrichissement des champs dérivés
        numero_equipe = e.get("numeroEquipe")
        if numero_equipe is not None:
            try:
                # Normalise en str simple ("1", "2", ...)
                numero_equipe = str(int(numero_equipe))
            except (TypeError, ValueError):
                numero_equipe = str(numero_equipe)

        categorie_code = cat.get("code", "") or ""
        # Suffixe de genre compact pour le label ("M"/"F" ou "")
        sexe_suffix = ""
        if sexe_field == "M":
            sexe_suffix = "M"
        elif sexe_field == "F":
            sexe_suffix = "F"

        # Construction d'un label prêt pour les agents, ex: "Stade Clermontois U11M1"
        base_cat = f"{categorie_code}{sexe_suffix}".strip()
        num_suffix = numero_equipe or ""
        cat_label = f"{base_cat}{num_suffix}" if base_cat or num_suffix else ""
        team_label = f"{club_nom} {cat_label}".strip()

        # Phase/label si disponible dans la structure d'engagement
        phase_label = e.get("phase") or e.get("libellePhase") or None

        team_id = e.get("id")

        flat.append(
            {
                "team_id": team_id,
                "engagement_id": team_id,
                "numero_equipe": numero_equipe,
                "team_label": cat_label or team_label,
                "phase_label": phase_label,
                "nom_equipe": club_nom,
                "competition": nom_comp,
                "competition_id": comp.get("id"),
                "poule_id": poule.get("id"),
                "sexe": comp.get("sexe", ""),
                "categorie": categorie_code,
                "niveau": comp.get("competition_origine_niveau"),
            }
        )
    return flat


async def ffbb_next_match_service(
    *, organisme_id: int | str, categorie: str, numero_equipe: int | None = None
) -> dict[str, Any]:
    """Service interne pour ffbb_next_match.

    - sélectionne l'engagement correspondant à (organisme_id, categorie, numero_equipe)
    - charge la poule courante
    - retourne la prochaine rencontre non jouée.
    """
    org_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    # On filtre d'abord par catégorie (avec éventuelle info de genre)
    equipes = await ffbb_equipes_club_service(
        organisme_id=org_id_int,
        filtre=categorie,
    )

    if not equipes:
        return {
            "status": "not_found",
            "message": f"Aucune équipe trouvée pour la catégorie '{categorie}'.",
        }

    # Si numero_equipe est fourni, on garde seulement celles qui correspondent
    if numero_equipe is not None:
        want = str(numero_equipe)
        equipes = [
            e for e in equipes if (e.get("numero_equipe") or "").strip() == want
        ]
        if not equipes:
            return {
                "status": "not_found",
                "message": (
                    "Aucune équipe ne correspond à cette combinaison "
                    f"categorie={categorie!r}, numero_equipe={numero_equipe}."
                ),
            }

    # S'il reste plusieurs engagements, on ne choisit pas au hasard
    if len(equipes) > 1:
        return {
            "status": "ambiguous",
            "message": (
                "Plusieurs engagements correspondent à cette catégorie. "
                "Demandez à l'utilisateur de préciser la phase ou le numéro d'équipe.")
            ,
            "candidates": equipes,
        }

    team = equipes[0]
    poule_id = team.get("poule_id")
    if not poule_id:
        return {
            "status": "not_found",
            "message": "Aucune poule active trouvée pour cette équipe.",
        }

    poule = await get_poule_service(poule_id)
    rencontres = poule.get("rencontres") or []
    if not rencontres:
        return {
            "status": "not_found",
            "message": "Aucune rencontre trouvée dans la poule.",
        }

    tz = ZoneInfo("Europe/Paris")
    now = datetime.now(tz)

    def _parse_dt(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except Exception:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except Exception:
                    dt = None
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(tz)

    upcoming: list[tuple[datetime, dict[str, Any]]] = []
    for m in rencontres:
        joue = m.get("joue")
        res1 = m.get("resultatEquipe1", m.get("resultat_equipe1"))
        res2 = m.get("resultatEquipe2", m.get("resultat_equipe2"))

        # Match considéré non joué si flag joue == 0
        # ou si les scores sont absents/"None".
        if joue not in (0, "0", None):
            # joue == 1 → match joué
            continue
        if res1 not in (None, "", "None") or res2 not in (None, "", "None"):
            # des scores sont présents → on considère joué
            continue

        dt = _parse_dt(m.get("date_rencontre", m.get("date")))
        if dt is None:
            # On garde quand même, mais avec une date minimale pour le tri
            dt = datetime.max.replace(tzinfo=tz)
        if dt < now:
            # match déjà passé mais non marqué joué → on ignore
            continue
        upcoming.append((dt, m))

    if not upcoming:
        return {
            "status": "no_upcoming_match",
            "message": "Aucun match à venir trouvé pour cette équipe.",
        }

    upcoming.sort(key=lambda x: x[0])
    next_dt, next_match = upcoming[0]

    # Déterminer l'adversaire : si l'engagement 1/2 correspond à notre équipe.
    eng1 = next_match.get("idEngagementEquipe1")
    eng2 = next_match.get("idEngagementEquipe2")
    id_eng1 = eng1.get("id") if isinstance(eng1, dict) else eng1
    id_eng2 = eng2.get("id") if isinstance(eng2, dict) else eng2
    my_eng = team.get("engagement_id")

    eq1_name = next_match.get("nomEquipe1", next_match.get("nom_equipe1", ""))
    eq2_name = next_match.get("nomEquipe2", next_match.get("nom_equipe2", ""))

    if my_eng and id_eng1 and str(my_eng) == str(id_eng1):
        adversaire = eq2_name
        domicile = True
    elif my_eng and id_eng2 and str(my_eng) == str(id_eng2):
        adversaire = eq1_name
        domicile = False
    else:
        # Fallback sur les noms
        club_nom = (team.get("nom_equipe") or "").lower()
        if club_nom and club_nom in (eq1_name or "").lower():
            adversaire = eq2_name
            domicile = True
        elif club_nom and club_nom in (eq2_name or "").lower():
            adversaire = eq1_name
            domicile = False
        else:
            adversaire = eq2_name or eq1_name
            domicile = None

    lieu = next_match.get("nomSalle") or next_match.get("nom_salle") or ""
    ville = next_match.get("villeSalle") or next_match.get("ville_salle") or ""

    return {
        "status": "ok",
        "team": team,
        "match": {
            "poule_id": poule_id,
            "match_id": next_match.get("id"),
            "date": next_dt.isoformat(),
            "adversaire": adversaire,
            "domicile": domicile,
            "equipe1": eq1_name,
            "equipe2": eq2_name,
            "salle": lieu,
            "ville": ville,
        },
    }


async def ffbb_saison_bilan_service(
    *, organisme_id: int | str, categorie: str, numero_equipe: int
) -> dict[str, Any]:
    """Service interne pour ffbb_bilan_saison.

    Agrège le bilan de TOUTES les phases de la saison pour une équipe précise.

    Contrairement à ffbb_bilan_service (qui part d'un club_name ou d'une
    catégorie globale), cette fonction travaille à partir d'une équipe
    identifiée sans ambiguïté.
    """
    org_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    equipes = await ffbb_equipes_club_service(
        organisme_id=org_id_int,
        filtre=categorie,
    )
    if not equipes:
        return {
            "status": "not_found",
            "message": f"Aucune équipe trouvée pour la catégorie '{categorie}'.",
        }

    want_num = str(numero_equipe)
    equipes = [
        e for e in equipes if (e.get("numero_equipe") or "").strip() == want_num
    ]
    if not equipes:
        return {
            "status": "not_found",
            "message": (
                "Aucune équipe ne correspond à cette combinaison "
                f"categorie={categorie!r}, numero_equipe={numero_equipe}."
            ),
        }

    # Plusieurs phases possibles pour la même équipe : on les garde toutes.
    poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )
    if not poule_ids:
        return {
            "status": "not_found",
            "message": "Aucune poule associée à cette équipe.",
        }

    semaphore = asyncio.Semaphore(_MAX_POULE_FETCH_CONCURRENCY)

    async def _fetch_poule(pid: str) -> dict[str, Any] | Exception:
        async with semaphore:
            try:
                return await get_poule_service(pid)
            except Exception as e:  # déjà normalisé par get_poule_service
                return e

    poules_raw = await asyncio.gather(
        *[_fetch_poule(pid) for pid in poule_ids], return_exceptions=True
    )
    poules_map: dict[str, dict[str, Any]] = {
        pid: pd
        for pid, pd in zip(poule_ids, poules_raw, strict=False)
        if not isinstance(pd, Exception) and pd
    }

    # Agrégation par phase
    phases: list[dict[str, Any]] = []
    totaux = {
        "match_joues": 0,
        "gagnes": 0,
        "perdus": 0,
        "nuls": 0,
        "paniers_marques": 0,
        "paniers_encaisses": 0,
        "difference": 0,
    }

    club_nom = equipes[0].get("nom_equipe", "")

    for pid, poule_data in poules_map.items():
        classements = poule_data.get("classements", []) or []
        for entry in classements:
            eng = entry.get("id_engagement", {}) or {}
            entry_eng_id = str(eng.get("id", ""))
            if entry_eng_id not in {str(e["engagement_id"]) for e in equipes}:
                continue

            mj = int(entry.get("match_joues") or 0)
            g = int(entry.get("gagnes") or 0)
            d = int(entry.get("perdus") or 0)
            n = int(entry.get("nuls") or 0)
            pm = int(entry.get("paniers_marques") or 0)
            pe = int(entry.get("paniers_encaisses") or 0)
            diff = int(entry.get("difference") or 0)

            phase = {
                "competition": poule_data.get("nom", ""),
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
            phases.append(phase)

            totaux["match_joues"] += mj
            totaux["gagnes"] += g
            totaux["perdus"] += d
            totaux["nuls"] += n
            totaux["paniers_marques"] += pm
            totaux["paniers_encaisses"] += pe
            totaux["difference"] += diff

    phases.sort(key=lambda x: x["competition"])

    return {
        "status": "ok",
        "club": club_nom,
        "categorie": categorie,
        "numero_equipe": numero_equipe,
        "bilan_total": totaux,
        "phases": phases,
    }


# Dans ffbb_bilan_service, on garde _safe_call encapsulé mais on limite les appels
# directs supplémentaires dans _fetch_poule_bilan :
#
# async def _fetch_poule_bilan(pid: str) -> dict[str, Any] | Exception:
#     async with semaphore:
#         try:
#             return await get_poule_service(pid)
#         except McpError:
#             try:
#                 client = await get_client_async()
#                 poule = await _with_ffbb_semaphore(
#                     _safe_call(
#                         f"Poule {pid}", lambda: client.get_poule_async(poule_id=pid)
#                     )
#                 )
#                 return serialize_model(poule) or {}
#             except Exception as e:
#                 return e


# De même, get_calendrier_club_service utilise déjà get_poule_service qui
# bénéficie désormais du sémaphore global.
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
                        poule = await _with_ffbb_semaphore(
                            _safe_call_with_inflight(
                                f"Poule {pid}",
                                lambda: client.get_poule_async(poule_id=pid),
                            )
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
    *,
    force_refresh: bool = False,
) -> list[dict]:
    """Récupère le calendrier et les résultats d'un club.

    Workflow :
    - Recherche du club si seul le nom est fourni
    - Récupération des équipes via ffbb_equipes_club_service
    - Récupération de toutes les poules concernées
    - Agrégation des rencontres
    - Troncature éventuelle si trop de matchs (FFBB_MAX_CALENDAR_MATCHES)
    """
    cache_key = f"calendrier:{organisme_id or ''}:{(club_name or '').lower().strip()}:{categorie or ''}"

    async def _fetch() -> list[dict]:
        # 1. Résoudre les organismes cibles
        target_org_ids: list[str] = []

        if organisme_id:
            target_org_ids = [str(organisme_id)]
        elif club_name:
            orgs = await search_organismes_service(nom=club_name, limit=3)
            target_org_ids = [
                str(org.get("id"))
                for org in orgs
                if isinstance(org, dict) and org.get("id")
            ]

        # Dédupliquer / nettoyer
        target_org_ids = list(dict.fromkeys(oid for oid in target_org_ids if oid))
        if not target_org_ids:
            return []

        # 2. Récupérer les équipes engagées correspondant à la catégorie en parallèle
        eq_tasks = [
            ffbb_equipes_club_service(organisme_id=oid, filtre=categorie)
            for oid in target_org_ids
        ]
        eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

        equipes: list[dict[str, Any]] = []
        for res in eq_results:
            if isinstance(res, list):
                equipes.extend(res)
            elif isinstance(res, Exception):
                logger.error("Erreur lors de la récupération des équipes: %s", res)

        if not equipes:
            return []

        # Dédupliquer les équipes par engagement_id pour éviter les doublons de matchs
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
        seen_match_ids: set[Any] = set()
        all_matches: list[dict[str, Any]] = []

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

        # --- Tri robuste par date + flags temporels ---
        tz = ZoneInfo("Europe/Paris")
        now = datetime.now(tz)

        def _parse_match_datetime(raw: str | None) -> datetime | None:
            if not raw:
                return None
            # La plupart des dates FFBB sont au format ISO, on reste défensif.
            try:
                dt = datetime.fromisoformat(raw)
            except Exception:
                # Fallback: essayer sans timezone ou avec espace au lieu de T
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(raw, fmt)
                        break
                    except Exception:
                        dt = None
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt.astimezone(tz)

        # Attacher un datetime parsé temporaire pour le tri
        for m in all_matches:
            m["_dt"] = _parse_match_datetime(m.get("date"))

        # Tri décroissant: du plus récent au plus ancien. Si la date manque, on met en fin.
        all_matches.sort(key=lambda x: (x["_dt"] is None, x["_dt"] or now), reverse=True)

        # Déterminer played / futur
        played_indices: list[int] = []
        future_indices: list[int] = []

        for idx, m in enumerate(all_matches):
            dt = m.get("_dt")
            score1 = m.get("score_equipe1")
            score2 = m.get("score_equipe2")

            has_score = score1 not in (None, "") or score2 not in (None, "")
            is_past = dt <= now if dt is not None else has_score

            played = bool(has_score or is_past)
            m["played"] = played

            if played:
                played_indices.append(idx)
            else:
                future_indices.append(idx)

        last_played_idx = played_indices[0] if played_indices else None
        next_future_idx = future_indices[-1] if future_indices else None

        for idx, m in enumerate(all_matches):
            m["is_last_match"] = last_played_idx is not None and idx == last_played_idx
            m["is_next_match"] = next_future_idx is not None and idx == next_future_idx
            m.pop("_dt", None)

        try:
            max_matches = int(os.getenv("FFBB_MAX_CALENDAR_MATCHES", "300"))
        except ValueError:
            max_matches = 300

        effective = all_matches

        if len(effective) > max_matches:
            truncated = effective[:max_matches]
            warning = {
                "warning": (
                    "Résultat tronqué côté MCP: trop de matchs pour ce club/catégorie. "
                    "Affichage limité pour protéger les performances. "
                    "Affinez votre requête (catégorie précise, équipe 1/2, phase, etc.)."
                ),
                "total_initial": len(all_matches),
                "limite_appliquee": max_matches,
            }
            return truncated + [warning]

        return effective

    # force_refresh contourne le cache de calendrier, mais continue de bénéficier
    # de la déduplication inflight.
    if force_refresh:
        return await _fetch()

    return await _dedupe_inflight(
        cache=_cache_calendrier,
        cache_key=cache_key,
        inflight_map=_inflight_calendrier,
        make_coro=_fetch,
    )


async def _resolve_poule_ids_for_categorie(org_data: dict, categorie: str) -> list[int]:
    """Résout les poule_id pertinents pour une catégorie donnée.

    - org_data : dict issu de get_organisme_service (model_dump())
    - categorie : ex. "U11M", "U13F1" etc.

    """
    from mcp.shared.exceptions import ErrorData, McpError

    engagements = org_data.get("engagements") or []
    if not engagements:
        raise McpError(
            ErrorData(
                code=400,
                message="Aucune équipe engagée trouvée pour ce club.",
            )
        )

    parsed = parse_categorie(categorie)
    code = parsed.categorie

    matched_poule_ids: list[int] = []
    for eng in engagements:
        comp = eng.get("idCompetition") or {}
        cat_info = comp.get("categorie") or {}
        comp_code = (cat_info.get("code") or "").upper()

        if code and comp_code and comp_code != code:
            continue

        poule = eng.get("idPoule") or {}
        poule_id = poule.get("id")
        if poule_id is None:
            continue
        try:
            matched_poule_ids.append(int(poule_id))
        except (TypeError, ValueError):
            continue

    if not matched_poule_ids:
        raise McpError(
            ErrorData(
                code=404,
                message=(
                    f"Aucune poule trouvée pour la catégorie {categorie!r} "
                    "dans les engagements de ce club."
                ),
            )
        )

    return matched_poule_ids


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


async def ffbb_resolve_team_service(
    *,
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
) -> dict[str, Any]:
    """Résout une équipe unique d'un club pour une catégorie donnée.

    Retourne un objet structuré pour les agents :
      - `status`: "resolved" | "ambiguous" | "not_found"
      - `team`: équipe résolue (ou None si ambiguë / introuvable)
      - `candidates`: liste des équipes candidates (peut être vide)
      - `ambiguity`: message explicite en cas d'ambiguïté
    """
    if not club_name and not organisme_id:
        raise McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message="Fournir club_name ou organisme_id",
            )
        )

    if not categorie:
        raise McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message="Paramètre 'categorie' requis (ex: 'U11M1', 'U13F2').",
            )
        )

    # 1) Résoudre l'organisme si besoin
    target_org_ids: list[str] = []

    if organisme_id is not None:
        target_org_ids = [str(organisme_id)]
    elif club_name:
        orgs = await search_organismes_service(nom=club_name, limit=5)
        target_org_ids = [
            str(org.get("id"))
            for org in orgs
            if isinstance(org, dict) and org.get("id")
        ]

    target_org_ids = list(dict.fromkeys(oid for oid in target_org_ids if oid))
    if not target_org_ids:
        msg = (
            f"Club '{club_name}' introuvable" if club_name else "Organisme introuvable"
        )
        raise McpError(error=ErrorData(code=INTERNAL_ERROR, message=msg))

    # 2) Récupérer toutes les équipes candidates pour cette catégorie
    eq_tasks = [
        ffbb_equipes_club_service(organisme_id=oid, filtre=categorie)
        for oid in target_org_ids
    ]
    eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

    candidates: list[dict[str, Any]] = []
    for res in eq_results:
        if isinstance(res, list):
            candidates.extend(res)
        elif isinstance(res, Exception):
            logger.error("Erreur lors de la récupération des équipes: %s", res)

    # 3) Construire la réponse selon les règles métier
    if not candidates:
        return {
            "status": "not_found",
            "team": None,
            "candidates": [],
            "ambiguity": f"Aucune équipe trouvée pour la catégorie '{categorie}'",
        }

    if len(candidates) == 1:
        return {
            "status": "resolved",
            "team": candidates[0],
            "candidates": candidates,
            "ambiguity": None,
        }

    ambiguity_msg = (
        "Plusieurs équipes correspondent à cette catégorie. "
        "Ne choisis pas d'équipe par défaut. "
        "Demande à l'utilisateur de préciser le numéro d'équipe (1, 2, ...) "
        "et/ou la phase avant de continuer."
    )

    return {
        "status": "ambiguous",
        "team": None,
        "candidates": candidates,
        "ambiguity": ambiguity_msg,
    }
