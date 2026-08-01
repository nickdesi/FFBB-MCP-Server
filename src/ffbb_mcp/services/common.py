from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import threading
import time
import unicodedata
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from cachetools import TLRUCache, TTLCache
from httpx import HTTPStatusError
from mcp.shared.exceptions import ErrorData, McpError
from mcp.types import INTERNAL_ERROR

from ffbb_mcp._state import _read_positive_int_env, state
from ffbb_mcp.cache_strategy import get_static_ttl
from ffbb_mcp.persistent_cache import make_persistent_cache
from ffbb_mcp.utils import _DIACRITICS


async def get_client_async(*args, **kwargs):
    import ffbb_mcp.client

    return await ffbb_mcp.client.get_client_async(*args, **kwargs)


from ffbb_mcp.metrics import (
    dec_inflight,
    inc_inflight,
    record_cache_hit,
    record_cache_miss,
    record_call,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger("ffbb-mcp")

# ---------------------------------------------------------------------------
# Expressions régulières pré-compilées (Optimisation des performances)
# ---------------------------------------------------------------------------
_PHASE_EXTRACT_PATTERN = re.compile(r"Phase\s*(\d+)", re.IGNORECASE)
_NUMERIC_EXTRACT_PATTERN = re.compile(r"(\d+)")
_ELIMINATION_KEYWORDS = re.compile(
    r"(finale|1/2|demi[- ]fin|quart|play[- ]?off|coupe|barrage|promotion)",
    re.IGNORECASE,
)

# Limiter globalement le nombre d'appels concurrents vers l'API FFBB.
_MAX_CONCURRENT_FFBB = _read_positive_int_env("MAX_CONCURRENT_FFBB", 8)
_MAX_CALENDAR_MATCHES = _read_positive_int_env("FFBB_MAX_CALENDAR_MATCHES", 300)
_ffbb_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FFBB)

# Stale-While-Revalidate : sert la valeur en cache immédiatement même si elle
# approche de son expiration, et rafraîchit en arrière-plan. L'utilisateur ne
# subit ainsi jamais la latence (~400ms) d'un cache miss sur les données chaudes.
_SWR_ENABLED = os.environ.get("FFBB_SWR_ENABLED", "1").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Fraction du TTL au-delà de laquelle une entrée est considérée "stale" et
# déclenche un refresh en arrière-plan (0.75 = on rafraîchit dans le dernier
# quart du TTL).
_SWR_STALE_FRACTION = float(os.environ.get("FFBB_SWR_STALE_FRACTION", "0.75"))
# Timeout applicatif par tentative d'appel FFBB (sec). Indépendant des
# timeouts httpx : un appel qui pend ne bloque jamais la réponse MCP.
_API_TIMEOUT_SECONDS = float(os.environ.get("FFBB_API_TIMEOUT_SECONDS", "30"))

# Hooks simples pour les metrics de cache.
_cache_hit_hook: Callable[..., None] | None = record_cache_hit
_cache_miss_hook: Callable[..., None] | None = record_cache_miss

# Sentinel unique pour distinguer une clé absente d'une valeur falsy.
_CACHE_MISS_SENTINEL: object = object()

_PARIS_TZ = ZoneInfo("Europe/Paris")


def _freshness_meta(
    *,
    source: str = "ffbb_api_live",
    cache: str | None = None,
    ttl_seconds: int | None = None,
    force_refresh_supported: bool = False,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "source": source,
        "generated_at": datetime.now(_PARIS_TZ).isoformat(),
        "timezone": "Europe/Paris",
    }
    if cache:
        meta["cache"] = cache
    if ttl_seconds is not None:
        meta["ttl_seconds"] = ttl_seconds
    if force_refresh_supported:
        meta["force_refresh_supported"] = True
    return meta


from functools import lru_cache


@lru_cache(maxsize=512)
def _normalize_name(value: str) -> str:
    """Normalise un nom (strip, upper, supprime les accents sans perdre de caractères)."""
    if not value:
        return ""
    s = value.strip().upper()
    if s.isascii():
        return s
    # ⚡ Bolt: Fast-path via C-optimized str.translate instead of list comprehension
    # yields an ~2.5x speedup for strings containing accents.
    return unicodedata.normalize("NFD", s).translate(_DIACRITICS)


def _coerce_numeric_id(value: int | str, label: str) -> int:
    """Convertit un identifiant en entier avec message d'erreur explicite."""
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message=(
                    f"{label} invalide: '{value}'. Un identifiant numérique est requis. "
                    "Utilisez l'id retourné par ffbb_search ou ffbb_club(action='equipes')."
                ),
            )
        ) from e


_BILAN_STAT_FIELDS: tuple[str, ...] = (
    "match_joues",
    "gagnes",
    "perdus",
    "nuls",
    "paniers_marques",
    "paniers_encaisses",
    "difference",
)


def _new_bilan_totals() -> dict[str, int]:
    return dict.fromkeys(_BILAN_STAT_FIELDS, 0)


def _extract_and_accumulate_bilan(
    entry: dict[str, Any], totaux: dict[str, int]
) -> dict[str, int]:
    stats: dict[str, int] = {}
    for f in _BILAN_STAT_FIELDS:
        v = int(entry.get(f) or 0)
        stats[f] = v
        totaux[f] += v

    # Intégrer les forfaits et défauts aux défaites ("perdus") pour la cohérence J = V + D + N
    forfaits = int(entry.get("nombre_forfaits") or 0)
    defauts = int(entry.get("nombre_defauts") or 0)
    if forfaits or defauts:
        addition = forfaits + defauts
        stats["perdus"] += addition
        totaux["perdus"] += addition

    return stats


def _extract_phase_num(label: str | None) -> int:
    """Extrait le numéro de phase d'un libellé (ex: 'Phase 3' -> 3)."""
    if not label:
        return 1

    # ⚡ Bolt: Fast-path via substring check avoids executing the
    # re.IGNORECASE regex engine when "phase" isn't present at all.
    # Bypassing the regex engine provides a ~35% speedup for non-matching strings.
    if "Phase" not in label and "phase" not in label and "PHASE" not in label:
        return 1

    match = _PHASE_EXTRACT_PATTERN.search(label)
    if match:
        # _PHASE_EXTRACT_PATTERN captures only digits (\d+), so ValueError is impossible
        return int(match.group(1))
    return 1


def _detect_phase_type(competition: str | None) -> str:
    """Détecte le type de phase à partir du nom de compétition."""
    if not competition:
        return "poule"

    # ⚡ Bolt: Fast-path literal check avoids executing the complex re.IGNORECASE
    # regex for the majority case ("poule" phase without any elimination keywords).
    # This provides a ~50% speedup.
    c = competition.lower()
    if (
        "coupe" in c
        or "play" in c
        or "final" in c
        or "demi" in c
        or "1/2" in c
        or "quart" in c
        or "barrage" in c
        or "promotion" in c
    ):
        return "elimination" if _ELIMINATION_KEYWORDS.search(competition) else "poule"
    return "poule"


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse une date FFBB en datetime avec la timezone spécifiée."""
    if not raw:
        return None
    tz = _PARIS_TZ

    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except ValueError:
        return None


def _notify_cache_hit(cache_name: str) -> None:
    import ffbb_mcp.services

    hook = getattr(ffbb_mcp.services, "_cache_hit_hook", None)
    if hook is not None:
        try:
            hook(cache_name)
        except Exception:
            logger.debug("cache hit hook failed", exc_info=True)


def _notify_cache_miss(cache_name: str, reason: str = "not_found") -> None:
    import ffbb_mcp.services

    hook = getattr(ffbb_mcp.services, "_cache_miss_hook", None)
    if hook is not None:
        try:
            hook(cache_name, reason)
        except TypeError:
            hook(cache_name)
        except Exception:
            logger.debug("cache miss hook failed", exc_info=True)


def _extract_salle_id(data: dict[str, Any]) -> str | None:
    raw_salle = data.get("salle") or data.get("idSalle") or data.get("id_salle")
    if isinstance(raw_salle, dict):
        raw_salle = raw_salle.get("id") or raw_salle.get("salle_id")
    if raw_salle in (None, ""):
        return None
    return str(raw_salle)


def _format_salle_address(salle: dict[str, Any]) -> str | None:
    parts = [
        salle.get("adresse") or salle.get("adresse1"),
        salle.get("code_postal") or salle.get("codePostal"),
        salle.get("ville") or salle.get("commune"),
    ]
    address = " ".join([str(part).strip() for part in parts if part])
    return address or None


# TTL configurables pour les caches
def _ttu_bilan(k, v, now):
    ttl = (
        v.get("_ttl", get_static_ttl("bilan"))
        if isinstance(v, dict)
        else get_static_ttl("bilan")
    )
    return now + ttl


def _ttu_poule(k, v, now):
    ttl = (
        v.get("_ttl", get_static_ttl("poule"))
        if isinstance(v, dict)
        else get_static_ttl("poule")
    )
    return now + ttl


def _ttu_calendrier(k, v, now):
    return now + _read_positive_int_env(
        "FFBB_CACHE_TTL_CALENDRIER", get_static_ttl("calendrier")
    )


# Initialisation des caches sur l'état global
# Les caches sont enveloppés dans un cache persistant (SQLite) quand
# FFBB_SERVICE_CACHE_PERSIST=1 : les entrées encore dans leur TTL sont
# réutilisées d'un redémarrage à l'autre (accélère les démarrages stdio
# à froid) sans jamais servir de donnée périmée.

state.cache_lives = make_persistent_cache(
    TTLCache(
        maxsize=1,
        ttl=_read_positive_int_env("FFBB_CACHE_TTL_LIVES", get_static_ttl("lives")),
    ),
    "lives",
)
state.cache_search = make_persistent_cache(
    TTLCache(
        maxsize=256,
        ttl=_read_positive_int_env("FFBB_CACHE_TTL_SEARCH", get_static_ttl("search")),
    ),
    "search",
)
state.cache_competition = make_persistent_cache(
    TTLCache(
        maxsize=128,
        ttl=_read_positive_int_env(
            "FFBB_CACHE_TTL_DETAIL", get_static_ttl("organisme")
        ),
    ),
    "competition",
)
state.cache_organisme = make_persistent_cache(
    TTLCache(
        maxsize=128,
        ttl=_read_positive_int_env(
            "FFBB_CACHE_TTL_DETAIL", get_static_ttl("organisme")
        ),
    ),
    "organisme",
)
state.cache_saisons = make_persistent_cache(
    TTLCache(
        maxsize=128,
        ttl=_read_positive_int_env(
            "FFBB_CACHE_TTL_DETAIL", get_static_ttl("organisme")
        ),
    ),
    "saisons",
)
state.cache_calendrier = make_persistent_cache(
    TLRUCache(maxsize=64, ttu=_ttu_calendrier),
    "calendrier",
    ttl_provider=lambda _v: get_static_ttl("calendrier"),
)
state.cache_bilan = make_persistent_cache(
    TLRUCache(maxsize=64, ttu=_ttu_bilan),
    "bilan",
    ttl_provider=lambda _v: get_static_ttl("bilan"),
)
state.cache_poule = make_persistent_cache(
    TLRUCache(maxsize=256, ttu=_ttu_poule),
    "poule",
)
state.cache_classement = make_persistent_cache(
    TLRUCache(maxsize=256, ttu=_ttu_poule),
    "classement",
)
state.cache_salle = make_persistent_cache(
    TTLCache(
        maxsize=1024,
        ttl=_read_positive_int_env("FFBB_CACHE_TTL_SALLE", get_static_ttl("salle")),
    ),
    "salle",
)
state.cache_resolve_club = make_persistent_cache(
    TTLCache(
        maxsize=256,
        ttl=_read_positive_int_env("FFBB_CACHE_TTL_RESOLVE_CLUB", 3600),
    ),
    "resolve_club",
)
state.cache_equipes = make_persistent_cache(
    TTLCache(
        maxsize=256,
        ttl=_read_positive_int_env("FFBB_CACHE_TTL_EQUIPES", 3600),
    ),
    "equipes",
)

_inflight_locks: dict[int, asyncio.Lock] = {}
_inflight_locks_guard = threading.Lock()
state.inflight_detail = {}
state.inflight_search = {}
state.inflight_calendrier = {}
state.inflight_bilan = {}
state.inflight_poule = {}


def _get_inflight_lock(
    inflight_map: dict[str, asyncio.Task[Any]] | None = None,
) -> asyncio.Lock:
    """Retourne un verrou asyncio dédié à une map inflight donnée.

    Au lieu d'un unique verrou global qui sérialise toutes les déduplications
    (bilan, poule, search, detail, calendrier), on utilise un verrou par map.
    Cela réduit la contention en mode HTTP/streamable concurent.
    """
    key = id(inflight_map) if inflight_map is not None else 0
    lock = _inflight_locks.get(key)
    if lock is None:
        with _inflight_locks_guard:
            lock = _inflight_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                _inflight_locks[key] = lock
    return lock


def get_cache_ttls() -> dict[str, int]:
    return {
        "lives": int(state.cache_lives.ttl) if state.cache_lives is not None else -1,
        "search": int(state.cache_search.ttl) if state.cache_search is not None else -1,
        "detail": int(state.cache_competition.ttl)
        if state.cache_competition is not None
        else -1,
        "competition": int(state.cache_competition.ttl)
        if state.cache_competition is not None
        else -1,
        "organisme": int(state.cache_organisme.ttl)
        if state.cache_organisme is not None
        else -1,
        "saisons": int(state.cache_saisons.ttl)
        if state.cache_saisons is not None
        else -1,
        "calendrier": _read_positive_int_env(
            "FFBB_CACHE_TTL_CALENDRIER", get_static_ttl("calendrier")
        ),
        "bilan": _read_positive_int_env(
            "FFBB_CACHE_TTL_BILAN", get_static_ttl("bilan")
        ),
        "poule": _read_positive_int_env(
            "FFBB_CACHE_TTL_POULE", get_static_ttl("poule")
        ),
        "salle": _read_positive_int_env(
            "FFBB_CACHE_TTL_SALLE", get_static_ttl("salle")
        ),
        "resolve_club": _read_positive_int_env("FFBB_CACHE_TTL_RESOLVE_CLUB", 3600),
    }


async def _with_ffbb_semaphore(coro):
    async with _ffbb_semaphore:
        return await coro


def handle_api_error(e: Exception) -> McpError:
    if isinstance(e, McpError):
        return e

    error_msg = str(e)
    logger.error("FFBB API Error: %s", error_msg, exc_info=True)

    if isinstance(e, HTTPStatusError):
        status = e.response.status_code
        if status == 404:
            return McpError(
                error=ErrorData(
                    code=INTERNAL_ERROR,
                    message=(
                        "Ressource FFBB introuvable (404). Action conseillée: vérifiez l'identifiant "
                        "numérique ou relancez ffbb_search(type='organismes') pour résoudre le club."
                    ),
                )
            )
        if status in (401, 403):
            return McpError(
                error=ErrorData(
                    code=INTERNAL_ERROR,
                    message=(
                        "Accès FFBB refusé (401/403). Action conseillée: vérifiez la configuration "
                        "d'accès FFBB et réessayez ensuite."
                    ),
                )
            )
        if status == 429:
            return McpError(
                error=ErrorData(
                    code=INTERNAL_ERROR,
                    message=(
                        "Rate-limit FFBB atteint (429). Action conseillée: réduisez les appels parallèles "
                        "et réessayez dans quelques secondes."
                    ),
                )
            )

    error_type = type(e).__name__
    if "timeout" in error_type.lower() or "timeout" in error_msg.lower():
        return McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message=(
                    "Timeout API FFBB. Action conseillée: réessayez dans quelques secondes; "
                    "si la fraîcheur live n'est pas nécessaire, évitez force_refresh=True."
                ),
            )
        )

    return McpError(
        error=ErrorData(
            code=INTERNAL_ERROR,
            message=(
                f"Erreur API FFBB ({error_type}): {error_msg}. Action conseillée: "
                "vérifiez les paramètres, puis réessayez ou relancez une recherche FFBB."
            ),
        )
    )


async def _safe_call(
    operation_name: str,
    coro: Callable[[], Coroutine[Any, Any, Any]],
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
) -> Any:
    logger.debug("Début exécution: %s", operation_name)

    if not callable(coro):
        raise ValueError(
            f"'_safe_call' expects a callable factory (e.g. lambda: coro()), got {type(coro)}."
        )
    make_coro = coro

    last_exc: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        t0 = time.perf_counter()
        try:
            current_coro = make_coro()
            async with asyncio.timeout(_API_TIMEOUT_SECONDS):
                result = await current_coro
            record_call(time.perf_counter() - t0, is_error=False)
            logger.debug("Succès: %s (attempt %d)", operation_name, attempt)
            return result
        except Exception as e:
            record_call(time.perf_counter() - t0, is_error=True)
            last_exc = e

            retriable = _is_retriable_error(e)

            if attempt >= retries or not retriable:
                raise handle_api_error(e) from e

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

    if last_exc is not None:
        raise handle_api_error(last_exc) from last_exc
    return None


def _is_retriable_error(e: Exception) -> bool:
    # TimeoutError est transitoire et couvre aussi asyncio.TimeoutError
    # et socket.timeout (dont il est la classe de base).
    if isinstance(e, TimeoutError):
        return True

    if isinstance(e, HTTPStatusError):
        status = getattr(e.response, "status_code", None)
        if status == 429:
            return True
        if status in (502, 503, 504):
            return True

    errname = type(e).__name__.lower()
    msg = str(e).lower()
    return any(
        keyword in errname or keyword in msg
        for keyword in ["timeout", "connection", "network", "temporary"]
    )


async def _safe_call_with_inflight(
    operation_name: str,
    coro_factory,
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
) -> Any:
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


def _cache_get(
    cache: Any,
    key: Any,
    cache_name: str,
    record_miss: bool = True,
) -> Any | None:
    if cache is None:
        return None
    val = cache.get(key, _CACHE_MISS_SENTINEL)
    if val is not _CACHE_MISS_SENTINEL:
        _notify_cache_hit(cache_name)
        return val
    if record_miss:
        _notify_cache_miss(cache_name)
    return None


def _cache_set(cache: Any, key: Any, val: Any, cache_name: str) -> None:
    if cache is None or val is None:
        return
    try:
        cache[key] = val
        # Horodatage du dernier fetch réel pour le SWR.
        state.swr_last_fetch[f"{cache_name}:{key}"] = time.monotonic()
    except TypeError, ValueError:
        logger.debug(
            "Impossible d'écrire dans le cache %s",
            cache_name,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Stale-While-Revalidate
# ---------------------------------------------------------------------------
def _swr_is_stale(cache_name: str, key: Any, ttl: float) -> bool:
    """Vrai si l'entrée dépasse la fraction "stale" de son TTL depuis le dernier fetch."""
    if not _SWR_ENABLED or ttl <= 0:
        return False
    sk = f"{cache_name}:{key}"
    last = state.swr_last_fetch.get(sk)
    if last is None:
        return True
    return (time.monotonic() - last) >= _SWR_STALE_FRACTION * ttl


def _swr_schedule(
    cache_name: str,
    key: Any,
    make_coro: Callable[[], Any],
    cache: Any = None,
) -> None:
    """Déclenche (fire-and-forget, dédupliqué) un refresh en arrière-plan.

    Si ``cache`` est fourni, le résultat du refresh est (ré)écrit dans le cache,
    ce qui permet d'utiliser cette fonction avec des ``make_coro`` qui ne
    persistent pas eux-mêmes (ex: ``_fetch`` des poules/classements).
    """
    name = f"{cache_name}:{key}"
    existing = state.swr_tasks.get(name)
    if existing is not None and not existing.done():
        return

    async def _run() -> None:
        try:
            result = await make_coro()
            if cache is not None and result is not None:
                _cache_set(cache, key, result, cache_name)
        except Exception:  # pragma: no cover - robustness
            logger.debug("SWR refresh '%s' échoué", name, exc_info=True)
        finally:
            state.swr_tasks.pop(name, None)

    try:
        state.swr_tasks[name] = asyncio.ensure_future(_run())
    except RuntimeError:
        # Pas de loop en cours (ex: import hors contexte async) → on ignore.
        logger.debug("SWR: impossible de planifier le refresh '%s' (pas de loop)", name)


async def _swr_serve(
    cache: Any,
    key: Any,
    cache_name: str,
    ttl: float,
    make_fetch_coro: Callable[[], Any],
) -> Any:
    """Sert depuis le cache ; si l'entrée est stale, la renvoie et rafraîchit en arrière-plan.

    ``make_fetch_coro`` est une fabrique de coroutine qui effectue le fetch réseau
    *complet* (fetch + enrichissement + écriture dans le cache) — exactement le
    chemin utilisé en cas de miss. En présence d'une entrée valide mais stale,
    on la renvoie immédiatement sans attendre le réseau, et on planifie son
    rafraîchissement asynchrone.
    """
    cached = _cache_get(cache, key, cache_name, record_miss=False)
    if cached is not None:
        if _swr_is_stale(cache_name, key, ttl):
            _swr_schedule(cache_name, key, make_fetch_coro, cache)
        return cached
    return await make_fetch_coro()


async def _dedupe_inflight(
    *,
    cache: TTLCache | TLRUCache | None,
    cache_key: str,
    inflight_map: dict[str, asyncio.Task[Any]],
    make_coro,
    cache_name: str,
    swr_ttl: float | None = None,
) -> Any:
    if cache is not None:
        cached = _cache_get(cache, cache_key, cache_name)
        if cached is not None:
            # Stale-While-Revalidate : on sert l'entrée valide mais stale
            # immédiatement, et on la rafraîchit en arrière-plan.
            if swr_ttl is not None and _swr_is_stale(cache_name, cache_key, swr_ttl):
                _swr_schedule(cache_name, cache_key, make_coro, cache)
            return cached

    async with _get_inflight_lock(inflight_map):
        if cache is not None:
            cached = _cache_get(cache, cache_key, cache_name, record_miss=False)
            if cached is not None:
                return cached
        existing = inflight_map.get(cache_key)
        if existing is None:
            existing = asyncio.create_task(make_coro())
            inflight_map[cache_key] = existing

    try:
        result = await existing
        if cache is not None:
            _cache_set(cache, cache_key, result, cache_name)
        return result
    finally:
        async with _get_inflight_lock(inflight_map):
            if inflight_map.get(cache_key) is existing:
                inflight_map.pop(cache_key, None)


async def _dedupe_inflight_detail(
    cache_key: str,
    make_coro,
    cache_name: str = "detail",
    cache: TTLCache | TLRUCache | None = None,
) -> Any:
    return await _dedupe_inflight(
        cache=cache,
        cache_key=cache_key,
        inflight_map=state.inflight_detail,
        make_coro=make_coro,
        cache_name=cache_name,
    )
