from __future__ import annotations

import asyncio
import logging
import random
import re
import threading
import time
import unicodedata
from collections.abc import Callable, Coroutine  # noqa: TC003
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

from cachetools import TLRUCache, TTLCache
from httpx import HTTPStatusError
from mcp.shared.exceptions import ErrorData, McpError
from mcp.types import INTERNAL_ERROR

from ffbb_mcp._state import _read_positive_int_env, state
from ffbb_mcp.aliases import enrich_acronym_cache, normalize_query
from ffbb_mcp.cache_strategy import get_poule_ttl, get_static_ttl
from ffbb_mcp.client import get_client_async
from ffbb_mcp.metrics import (
    dec_inflight,
    inc_inflight,
    record_cache_hit,
    record_cache_miss,
    record_call,
)
from ffbb_mcp.utils import (
    ParsedCategorie,
    format_team_name,
    parse_categorie,
    serialize_model,
)

logger = logging.getLogger("ffbb-mcp")

# ---------------------------------------------------------------------------
# Expressions régulières pré-compilées (Optimisation des performances)
# ---------------------------------------------------------------------------
# Le pré-calcul des regex évite le surcoût de la compilation dynamique lors
# des cache misses ou des fonctions appelées fréquemment.

_PHASE_EXTRACT_PATTERN = re.compile(r"Phase\s*(\d+)", re.IGNORECASE)
_NUMERIC_EXTRACT_PATTERN = re.compile(r"(\d+)")
_ELIMINATION_KEYWORDS = re.compile(
    r"(finale|1/2|demi[- ]fin|quart|play[- ]?off|coupe|barrage|promotion)",
    re.IGNORECASE,
)


# Limiter globalement le nombre d'appels concurrents vers l'API FFBB.
# Valeur par défaut prudente, surchargable via l'env MAX_CONCURRENT_FFBB.
_MAX_CONCURRENT_FFBB = _read_positive_int_env("MAX_CONCURRENT_FFBB", 8)
_MAX_CALENDAR_MATCHES = _read_positive_int_env("FFBB_MAX_CALENDAR_MATCHES", 300)
_ffbb_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FFBB)

# Hooks simples pour les metrics de cache. Ils sont no-op par défaut et peuvent
# être surchargés depuis metrics.py via une fonction d'initialisation.
_cache_hit_hook: Callable[..., None] | None = record_cache_hit
_cache_miss_hook: Callable[..., None] | None = record_cache_miss

# Sentinel unique pour distinguer une clé absente d'une valeur falsy (None, 0, [], {}).
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


@lru_cache(maxsize=128)
def _extract_phase_num(label: str | None) -> int:
    """Extrait le numéro de phase d'un libellé (ex: 'Phase 3' -> 3).
    Si non trouvé ou absent, retourne 1.
    """
    if not label:
        return 1
    match = _PHASE_EXTRACT_PATTERN.search(label)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return 1


def _detect_phase_type(competition: str | None) -> str:
    """Detecte le type de phase a partir du nom de competition.

    Retourne ``"elimination"`` si le champ contient un terme eliminiatoire
    (finale, 1/2, quart, play-off, coupe, barrage, promotion), sinon ``"poule"``.
    """
    if not competition:
        return "poule"
    return "elimination" if _ELIMINATION_KEYWORDS.search(competition) else "poule"


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse une date FFBB en datetime avec la timezone spécifiée."""
    if not raw:
        return None
    tz = _PARIS_TZ

    try:
        # Fast path for Python 3.11+: fromisoformat natively supports spaces.
        # This replaces the costly fallback loop and string replace.
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except ValueError:
        pass

    # Fallback pour Python <= 3.10 : fromisoformat ne supporte pas
    # toujours l'espace comme séparateur. On le remplace par 'T' via
    # concatenation (plus rapide que str.replace) si la date fait 19 chars.
    if type(raw) is str and len(raw) == 19 and raw[10] == " ":
        try:
            dt = datetime.fromisoformat(raw[:10] + "T" + raw[11:])
            if dt.tzinfo is None:
                return dt.replace(tzinfo=tz)
            return dt.astimezone(tz)
        except ValueError:
            pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=tz)
            return dt.astimezone(tz)
        except ValueError:
            pass

    return None


def _notify_cache_hit(cache_name: str) -> None:
    if _cache_hit_hook is not None:
        try:
            _cache_hit_hook(cache_name)
        except Exception:  # sécurité: jamais d'exception dans un hook de métriques
            logger.debug("cache hit hook failed", exc_info=True)


def _notify_cache_miss(cache_name: str, reason: str = "not_found") -> None:
    if _cache_miss_hook is not None:
        try:
            _cache_miss_hook(cache_name, reason)
        except TypeError:
            _cache_miss_hook(cache_name)
        except Exception:  # idem
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
    address = " ".join(str(part).strip() for part in parts if part)
    return address or None


async def _enrich_with_salle_details(
    data: dict[str, Any], client: Any
) -> dict[str, Any]:
    salle_id = _extract_salle_id(data)
    if not salle_id or data.get("salle_details"):
        return data

    salle = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            f"Get salle {salle_id}",
            lambda: client.get_salle_async(salle_id),
        )
    )
    salle_data = serialize_model(salle) if salle is not None else {}
    if isinstance(salle_data, dict) and salle_data:
        data["salle_details"] = salle_data
        adresse = _format_salle_address(salle_data)
        if adresse:
            data["adresse_salle"] = adresse
    return data


async def _enrich_matches_with_salle_details(matches: list[dict[str, Any]]) -> None:
    salle_ids = list(
        dict.fromkeys(salle_id for m in matches if (salle_id := _extract_salle_id(m)))
    )
    if not salle_ids:
        return

    client = await get_client_async()
    salle_cache: dict[str, dict[str, Any]] = {}
    for salle_id in salle_ids:
        salle = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Get salle {salle_id}",
                lambda salle_id=salle_id: client.get_salle_async(salle_id),
            )
        )
        salle_data = serialize_model(salle) if salle is not None else {}
        if isinstance(salle_data, dict) and salle_data:
            salle_cache[salle_id] = salle_data

    for match in matches:
        salle_id = _extract_salle_id(match)
        if not salle_id or salle_id not in salle_cache:
            continue
        match["salle_details"] = salle_cache[salle_id]
        adresse = _format_salle_address(salle_cache[salle_id])
        if adresse:
            match["adresse_salle"] = adresse


# ---------------------------------------------------------------------------
# Cache service-level (en mémoire, complémentaire au cache SQLite HTTP)
# ---------------------------------------------------------------------------


# TTL configurables via variables d'environnement pour affiner par type de données.
# Les données vraiment temps-réel (lives, poules) ont des TTL courts (15s).
# Les données qui ne changent qu'après des matchs joués (bilans, calendriers) ont des TTL longs.
# La protection contre le burst est assurée par le mécanisme de déduplication "inflight" (_dedupe_inflight).
def _ttu_bilan(k, v, now):
    ttl = (
        v.get("_ttl", get_static_ttl("bilan"))
        if isinstance(v, dict)
        else get_static_ttl("bilan")
    )
    return now + ttl


def _ttu_poule(k, v, now):
    # Retrieve ttl from the wrapped object, fallback to default get_static_ttl
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


# TTL des caches froids : le TTL est calculé une seule fois à l'initialisation (au chargement du module).
# Changer la variable d'environnement à chaud n'aura pas d'effet sur ces caches. C'est le comportement intentionnel
# pour éviter des ré-évaluations constantes pour des données relativement statiques ou basées sur un restart du serveur.
state.cache_lives = TTLCache(
    maxsize=1,
    ttl=_read_positive_int_env("FFBB_CACHE_TTL_LIVES", get_static_ttl("lives")),
)
state.cache_search = TTLCache(
    maxsize=256,
    ttl=_read_positive_int_env("FFBB_CACHE_TTL_SEARCH", get_static_ttl("search")),
)
state.cache_competition = TTLCache(
    maxsize=128,
    ttl=_read_positive_int_env("FFBB_CACHE_TTL_DETAIL", get_static_ttl("organisme")),
)
state.cache_organisme = TTLCache(
    maxsize=128,
    ttl=_read_positive_int_env("FFBB_CACHE_TTL_DETAIL", get_static_ttl("organisme")),
)
state.cache_saisons = TTLCache(
    maxsize=128,
    ttl=_read_positive_int_env("FFBB_CACHE_TTL_DETAIL", get_static_ttl("organisme")),
)
state.cache_calendrier = TLRUCache(
    maxsize=64,
    ttu=_ttu_calendrier,
)
state.cache_bilan = TLRUCache(maxsize=64, ttu=_ttu_bilan)
state.cache_poule = TLRUCache(maxsize=128, ttu=_ttu_poule)
# NOTE INTENTIONNEL : cache_classement réutilise _ttu_poule car les classements
# sont extraits des mêmes données de poule et partagent leur cycle de vie.
state.cache_classement = TLRUCache(maxsize=128, ttu=_ttu_poule)
_inflight_lock: asyncio.Lock | None = None
_inflight_lock_guard = threading.Lock()
state.inflight_detail = {}
state.inflight_search = {}
state.inflight_calendrier = {}
state.inflight_bilan = {}
state.inflight_poule = {}


def _get_inflight_lock() -> asyncio.Lock:
    """Retourne le lock inflight, en le créant lazily de façon thread-safe."""
    global _inflight_lock
    if _inflight_lock is None:
        with _inflight_lock_guard:
            if _inflight_lock is None:
                _inflight_lock = asyncio.Lock()
    return _inflight_lock


def get_cache_ttls() -> dict[str, int]:
    """Retourne les TTL (en secondes) pour chaque cache service-level.

    Cette fonction fournit une vue compacte et strictement typée des TTL,
    utilisable par un outil de version/status sans exposer les objets TTLCache.
    """

    return {
        # Return -1 if uninitialized to distinguish from an actual 0 TTL
        "lives": int(state.cache_lives.ttl) if state.cache_lives else -1,
        "search": int(state.cache_search.ttl) if state.cache_search else -1,
        "detail": int(state.cache_competition.ttl) if state.cache_competition else -1,
        "competition": int(state.cache_competition.ttl)
        if state.cache_competition
        else -1,
        "organisme": int(state.cache_organisme.ttl) if state.cache_organisme else -1,
        "saisons": int(state.cache_saisons.ttl) if state.cache_saisons else -1,
        "calendrier": _read_positive_int_env(
            "FFBB_CACHE_TTL_CALENDRIER", get_static_ttl("calendrier")
        ),
        "bilan": _read_positive_int_env(
            "FFBB_CACHE_TTL_BILAN", get_static_ttl("bilan")
        ),
        "poule": _read_positive_int_env(
            "FFBB_CACHE_TTL_POULE", get_static_ttl("poule")
        ),
    }


_MAX_POULE_FETCH_CONCURRENCY = _read_positive_int_env("FFBB_POULE_FETCH_CONCURRENCY", 8)


async def _with_ffbb_semaphore(coro):
    """Helper pour exécuter un appel réseau FFBB sous le sémaphore global.

    Cela encapsule la contrainte de concurrence en un seul endroit, ce qui rend
    plus simple l'utilisation dans les différents services.
    """

    async with _ffbb_semaphore:
        return await coro


def _cache_get(
    cache: TTLCache | TLRUCache | None,
    key: Any,
    cache_name: str,
    *,
    record_miss: bool = True,
) -> Any | None:
    """Wrapper centralisé pour lire un cache avec metrics hit/miss.

    Ce helper évite de dupliquer la logique de notification et permet de
    garder une sémantique uniforme sur tous les caches du module.

    Utilise un sentinel pour distinguer une valeur falsy stockée (None, 0, [], {})
    d'une clé réellement absente — évite les miss fantômes sur ces valeurs.
    """
    if cache is None:
        return None
    value = cache.get(key, _CACHE_MISS_SENTINEL)
    if value is not _CACHE_MISS_SENTINEL:
        _notify_cache_hit(cache_name)
        return value
    if record_miss:
        reason = "expired_or_absent" if len(cache) else "cold_start"
        _notify_cache_miss(cache_name, reason)
    return None


class _CacheSupportsSetItem(Protocol):
    def __setitem__(self, key: Any, value: Any) -> None: ...


class SupportsAssetUrl(Protocol):
    def get_asset_url(
        self,
        *,
        uuid: str,
        width: int | None = None,
        height: int | None = None,
        format: str | None = None,
        quality: int | None = None,
    ) -> str: ...


async def get_asset_url_service(
    uuid: str,
    width: int | None = None,
    height: int | None = None,
    format: str | None = None,
    quality: int | None = None,
) -> str:
    """Construit une URL d'asset Directus optimisée via le client V3."""
    client = cast("SupportsAssetUrl", await get_client_async())
    return client.get_asset_url(
        uuid=uuid,
        width=width,
        height=height,
        format=format,
        quality=quality,
    )


def _cache_set(
    cache: TTLCache | TLRUCache | None, key: Any, value: Any, cache_name: str
) -> None:
    if cache is not None:
        cast("_CacheSupportsSetItem", cache)[key] = value
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
    stats = {f: int(entry.get(f) or 0) for f in _BILAN_STAT_FIELDS}
    for f, v in stats.items():
        totaux[f] += v
    return stats


def _dedup_equipes_by_engagement(equipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Déduplique les équipes par engagement_id pour éviter les doublons de matchs."""
    deduped_equipes: list[dict[str, Any]] = []
    seen_engagement_ids: set[str] = set()
    for equipe in equipes:
        if not isinstance(equipe, dict):
            continue
        engagement_id = equipe.get("engagement_id")
        if engagement_id is None:
            deduped_equipes.append(equipe)
            continue
        engagement_key = str(engagement_id)
        if engagement_key in seen_engagement_ids:
            continue
        seen_engagement_ids.add(engagement_key)
        deduped_equipes.append(equipe)
    return deduped_equipes


# ---------------------------------------------------------------------------
# Gestion d'erreurs
# ---------------------------------------------------------------------------


def handle_api_error(e: Exception) -> McpError:
    """Formatage cohérent des erreurs API pour tous les outils."""
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

    # Distinguer les timeouts des autres erreurs
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
    """Exécute un appel API avec logging, error handling et retry/backoff.

    `coro` peut être soit une coroutine (non-réessayable), soit un "callable"
    zéro-argument qui retourne une nouvelle coroutine (réessayable).
    """
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
            result = await current_coro
            record_call(time.perf_counter() - t0, is_error=False)
            logger.debug("Succès: %s (attempt %d)", operation_name, attempt)
            return result
        except Exception as e:
            record_call(time.perf_counter() - t0, is_error=True)
            last_exc = e

            # Décider si l'erreur est réessayable
            retriable = _is_retriable_error(e)

            if attempt >= retries or not retriable:
                # plus de tentatives ou pas réessayable : lever l'erreur gérée
                raise handle_api_error(e) from e

            # backoff exponentiel avec jitter
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

    # Si on sort de la boucle sans retourner, lever la dernière exception formatée
    if last_exc is not None:
        raise handle_api_error(last_exc) from last_exc
    return None


def _is_retriable_error(e: Exception) -> bool:
    """Détermine si une erreur est réessayable."""
    if isinstance(e, HTTPStatusError):
        status = getattr(e.response, "status_code", None)
        if status == 429:  # Rate limiting
            return True
        if status in (502, 503, 504):  # Server errors
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


async def _dedupe_inflight_detail(
    cache_key: str,
    make_coro,
    cache_name: str = "detail",
    cache: TTLCache | TLRUCache | None = None,
) -> Any:
    """Déduplique les appels concurrents sur la même clé de détail."""
    return await _dedupe_inflight(
        cache=cache,
        cache_key=cache_key,
        inflight_map=state.inflight_detail,
        make_coro=make_coro,
        cache_name=cache_name,
    )


async def _dedupe_inflight(
    *,
    cache: TTLCache | TLRUCache | None,
    cache_key: str,
    inflight_map: dict[str, asyncio.Task[Any]],
    make_coro,
    cache_name: str,
) -> Any:
    """Déduplique les appels concurrents sur une clé et met en cache le résultat."""
    if cache is not None:
        cached = _cache_get(cache, cache_key, cache_name)
        if cached is not None:
            return cached

    async with _get_inflight_lock():
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
        async with _get_inflight_lock():
            if inflight_map.get(cache_key) is existing:
                inflight_map.pop(cache_key, None)


# ---------------------------------------------------------------------------
# Services -- Données en direct
# ---------------------------------------------------------------------------


async def get_lives_service() -> list[dict]:
    cached = _cache_get(state.cache_lives, "lives", "lives")
    if cached is not None:
        logger.debug("Cache hit: lives")
        return cached

    client = await get_client_async()
    lives = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            "Lives (Matchs en cours)", lambda: client.get_lives_async()
        )
    )
    lives_list = lives if isinstance(lives, list) else []
    result = [serialize_model(live) for live in lives_list]
    _cache_set(state.cache_lives, "lives", result, "lives")
    return result


async def get_saisons_service(active_only: bool = False) -> list[dict]:
    cache_key = f"saisons:{active_only}"
    cached = _cache_get(state.cache_saisons, cache_key, "saisons")
    if cached is not None:
        return cached

    client = await get_client_async()
    filter_criteria = '{"actif": {"$eq": true}}' if active_only else None
    saisons = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            "Saisons", lambda: client.get_saisons_async(filter_criteria=filter_criteria)
        )
    )
    saisons_list = saisons if isinstance(saisons, list) else []
    result = [serialize_model(s) for s in saisons_list]
    _cache_set(state.cache_saisons, cache_key, result, "saisons")
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

    return await _dedupe_inflight_detail(
        cache_key,
        _fetch,
        cache_name="competition",
        cache=state.cache_competition,
    )


async def get_poule_service(
    poule_id: int | str, *, force_refresh: bool = False
) -> dict:
    poule_id_int = _coerce_numeric_id(poule_id, "poule_id")
    cache_key = f"poule:{poule_id_int}"

    if force_refresh and state.cache_poule is not None:
        state.cache_poule.pop(cache_key, None)

    async def _fetch() -> dict:
        client = await get_client_async()
        poule = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Poule {poule_id_int}",
                lambda: client.get_poule_async(poule_id=poule_id_int),
            ),
        )
        data = serialize_model(poule) or {}

        # Enrichissement : rencontres non jouées (joue=0) groupées par équipe.
        # Permet au LLM de savoir sans ambiguïté si une phase est terminée
        # pour une équipe donnée, sans inférer depuis match_joues du classement.
        rencontres = data.get("rencontres", []) or []
        restantes_par_equipe: dict[str, list[dict]] = {}
        for r in rencontres:
            if r.get("joue") not in (0, "0"):
                continue
            for side in ("nomEquipe1", "nomEquipe2"):
                nom = r.get(side, "")
                if nom:
                    restantes_par_equipe.setdefault(nom, []).append(
                        {
                            "id": r.get("id"),
                            "date": r.get("date_rencontre"),
                            "domicile": r.get("nomEquipe1"),
                            "exterieur": r.get("nomEquipe2"),
                            "journee": r.get("numeroJournee"),
                        }
                    )
        data["rencontres_restantes_par_equipe"] = restantes_par_equipe
        data["phase_terminee"] = len(restantes_par_equipe) == 0
        comp_name = data.get("nom") or data.get("libelle") or ""
        data["phase_type"] = _detect_phase_type(comp_name)

        # Calculate dynamic TTL
        ttl = await get_poule_ttl(poule_id_int, get_lives_service)
        return {"_ttl": ttl, "data": data}

    # On utilise toujours le mécanisme de déduplication pour éviter de frapper
    # l'API FFBB plusieurs fois pour la même poule en parallèle.
    result = await _dedupe_inflight(
        cache=state.cache_poule,
        cache_key=cache_key,
        inflight_map=state.inflight_poule,
        make_coro=_fetch,
        cache_name="poule",
    )
    # Tri par date/heure — on remplace la liste plutôt que de muter in-place
    # pour ne pas corrompre la référence stockée dans le cache sous concurrence.
    if isinstance(result, dict) and "data" in result:
        rencontres = result["data"].get("rencontres", [])
        if rencontres:
            result["data"]["rencontres"] = sorted(
                rencontres,
                key=lambda r: (
                    r.get("date_reelle") or "9999",
                    r.get("heure_reelle") or "9999",
                ),
            )

    return (
        result.get("data", result)
        if isinstance(result, dict) and "_ttl" in result
        else result
    )


def format_poule_response(poule_data: dict) -> dict[str, Any]:
    """Formate les données brutes d'une poule pour la réponse MCP.

    Enrichit classements (equipe, logo_url) et rencontres (nomEquipe1/2 formatés).
    Applique la troncature configurable via FFBB_MAX_CALENDAR_MATCHES.
    """
    classements = poule_data.get("classements", [])
    formatted_classements = []
    for c in classements or []:
        eng = c.get("id_engagement", {}) or {}
        nom = eng.get("nom", "")
        num = eng.get("numero_equipe")
        c["equipe"] = format_team_name(nom, num)
        logo_id = (eng.get("logo") or {}).get("id")
        c["logo_url"] = (
            f"https://api.ffbb.com/assets/{logo_id}?height=220&fit=contain&format=avif"
            if logo_id
            else None
        )
        formatted_classements.append(c)

    rencontres = poule_data.get("rencontres", [])
    formatted_rencontres = []
    for m in rencontres or []:
        eng1 = m.get("idEngagementEquipe1", {}) or {}
        eng2 = m.get("idEngagementEquipe2", {}) or {}
        num1 = eng1.get("numeroEquipe") if isinstance(eng1, dict) else None
        num2 = eng2.get("numeroEquipe") if isinstance(eng2, dict) else None
        m["nomEquipe1"] = format_team_name(m.get("nomEquipe1", ""), num1)
        m["nomEquipe2"] = format_team_name(m.get("nomEquipe2", ""), num2)
        formatted_rencontres.append(m)

    res: dict[str, Any] = {
        "id": poule_data.get("id"),
        "nom": poule_data.get("libelle"),
        "classements": formatted_classements,
        "rencontres": formatted_rencontres,
        "_meta": _freshness_meta(
            cache="poule",
            ttl_seconds=poule_data.get("_ttl_seconds"),
            force_refresh_supported=True,
        ),
    }
    if formatted_rencontres:
        max_limit = _MAX_CALENDAR_MATCHES
        total_matches = len(formatted_rencontres)
        if total_matches > max_limit:
            truncated_rencontres = formatted_rencontres[:max_limit]
            truncated_rencontres.append(
                {
                    "warning": f"Résultat tronqué. Seulement {max_limit} rencontres sur {total_matches} affichées."
                }
            )
            res["rencontres"] = truncated_rencontres
            res["_truncated"] = True
            res["_omitted_count"] = total_matches - max_limit
            res["_total"] = total_matches
    return res


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

    return await _dedupe_inflight_detail(
        cache_key,
        _fetch,
        cache_name="organisme",
        cache=state.cache_organisme,
    )


async def ffbb_get_classement_service(
    poule_id: int | str,
    *,
    force_refresh: bool = False,
    target_organisme_id: int | str | None = None,
    target_num: int | str | None = None,
) -> list[dict[str, Any]]:
    poule_id_int = _coerce_numeric_id(poule_id, "poule_id")
    cache_key = (
        f"classement:{poule_id_int}:{target_organisme_id or ''}:{target_num or ''}"
    )

    if force_refresh and state.cache_classement is not None:
        state.cache_classement.pop(cache_key, None)

    cached = _cache_get(state.cache_classement, cache_key, "classement")
    if cached is not None:
        return (
            cached["data"] if isinstance(cached, dict) and "data" in cached else cached
        )

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
    raw = data.get("classements", data.get("classement", [])) or []
    if not isinstance(raw, list):
        raw = []

    flat: list[dict[str, Any]] = []
    target_org_str = str(target_organisme_id) if target_organisme_id else None
    target_num_str = str(target_num) if target_num else None

    for c in raw:
        if not isinstance(c, dict):
            continue
        eng = c.get("id_engagement", {}) or {}
        nom_equipe = eng.get("nom", "")
        num_equipe = eng.get("numero_equipe")
        # Identification du club via organisme_id ou rapprochement par nom (fallback)
        org_id = str(c.get("organisme_id") or eng.get("organisme_id") or "")

        is_target = False
        if target_org_str and org_id == target_org_str:
            if target_num_str:
                curr_num = str(num_equipe or "")
                if curr_num == target_num_str or not curr_num:
                    is_target = True
            else:
                is_target = True

        # Priorité 1 : organisme_logo_id (champ direct, toujours renseigné)
        # Priorité 2 : logo dans id_engagement (fallback si API change)
        logo_id = c.get("organisme_logo_id") or (eng.get("logo") or {}).get("id")
        logo_url = (
            f"https://api.ffbb.com/assets/{logo_id}?height=220&fit=contain&format=avif"
            if logo_id
            else None
        )

        flat.append(
            {
                "position": c.get("position"),
                "equipe": format_team_name(nom_equipe, num_equipe),
                "points": c.get("points"),
                "match_joues": c.get("match_joues"),
                "gagnes": c.get("gagnes"),
                "perdus": c.get("perdus"),
                "difference": c.get("difference"),
                "is_target": is_target,
                "paniers_marques": c.get("paniers_marques") or 0,
                "paniers_encaisses": c.get("paniers_encaisses") or 0,
                "logo_url": logo_url,
                "point_initiaux": c.get("point_initiaux"),
                "penalites_arbitrage": c.get("penalites_arbitrage"),
                "penalites_entraineur": c.get("penalites_entraineur"),
                "penalites_diverses": c.get("penalites_diverses"),
                "nombre_forfaits": c.get("nombre_forfaits"),
                "nombre_defauts": c.get("nombre_defauts"),
                "quotient": c.get("quotient"),
                "hors_classement": c.get("hors_classement"),
            }
        )
    # Calculate dynamic TTL using same logic as poule since it caches in state.cache_classement
    ttl = await get_poule_ttl(poule_id_int, get_lives_service)
    wrapped_flat = {"_ttl": ttl, "data": flat}
    _cache_set(state.cache_classement, cache_key, wrapped_flat, "classement")
    return flat


async def _search_generic(
    operation: str,
    method_name: str,
    query: str,
    limit: int = 20,
    filter_by: str | None = None,
    sort: list[str] | None = None,
) -> list[dict]:
    normalized_query = normalize_query(query)
    filter_part = filter_by or ""
    sort_part = ",".join(sort) if sort else ""
    cache_key = (
        f"search:{operation}:{normalized_query}:{limit}:{filter_part}:{sort_part}"
    )

    async def _fetch() -> list[dict]:
        # Lazy import to avoid heavy ffbb_data_client initialization at
        # module import time.

        client = await get_client_async()
        method = getattr(client, method_name)
        call_kwargs: dict[str, Any] = {}
        if filter_by:
            call_kwargs["filter_by"] = filter_by
        if sort:
            call_kwargs["sort"] = sort
        results = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Search {operation}: {query}",
                lambda: method(normalized_query, **call_kwargs),
            )
        )
        if not results or not results.hits:
            return []
        return [serialize_model(hit) for hit in results.hits[:limit]]

    return await _dedupe_inflight(
        cache=state.cache_search,
        cache_key=cache_key,
        inflight_map=state.inflight_search,
        make_coro=_fetch,
        cache_name="search",
    )


async def multi_search_service(nom: str, limit: int = 20) -> list[dict[str, Any]]:
    normalized_query = normalize_query(nom)
    cache_key = f"multi_search:{normalized_query}:{limit}"

    async def _fetch() -> list[dict[str, Any]]:
        # Lazy imports to avoid heavy ffbb_data_client initialization at
        # module import time.
        from ffbb_data_client.config import (
            MEILISEARCH_INDEX_COMPETITIONS,
            MEILISEARCH_INDEX_ORGANISMES,
            MEILISEARCH_INDEX_PRATIQUES,
            MEILISEARCH_INDEX_RENCONTRES,
            MEILISEARCH_INDEX_SALLES,
            MEILISEARCH_INDEX_TERRAINS,
            MEILISEARCH_INDEX_TOURNOIS,
        )
        from ffbb_data_client.models import MultiSearchQuery

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
        cache=state.cache_search,
        cache_key=cache_key,
        inflight_map=state.inflight_search,
        make_coro=_fetch,
        cache_name="search",
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
    if org_data is not None:
        data: dict[str, Any] | None = org_data
    elif organisme_id is not None:
        data = await get_organisme_service(organisme_id)
    else:
        return []
    if not data:
        return []

    raw = data.get("engagements", []) if isinstance(data, dict) else []
    all_teams: list[dict[str, Any]] = []
    club_nom = data.get("nom", "")

    parsed_filter: ParsedCategorie | None = parse_categorie(filtre) if filtre else None

    for e in raw:
        if not isinstance(e, dict):
            continue
        comp = e.get("idCompetition", {}) or {}
        poule = e.get("idPoule", {}) or {}
        cat = comp.get("categorie", {}) or {}
        nom_comp = comp.get("nom", "")
        sexe_field = (comp.get("sexe") or "").upper()

        # Enrichissement des champs dérivés
        numero_equipe = e.get("numeroEquipe")
        if numero_equipe is None and nom_comp:
            parsed_comp = parse_categorie(nom_comp)
            if parsed_comp.numero_equipe:
                numero_equipe = parsed_comp.numero_equipe

        if numero_equipe is not None:
            try:
                numero_equipe = str(int(numero_equipe))
            except (TypeError, ValueError):
                numero_equipe = str(numero_equipe)

        categorie_code = cat.get("code", "") or ""
        sexe_suffix = "M" if sexe_field == "M" else "F" if sexe_field == "F" else ""

        base_cat = f"{categorie_code}{sexe_suffix}".strip()
        num_suffix = numero_equipe or ""
        cat_label = f"{base_cat}{num_suffix}" if base_cat or num_suffix else ""
        team_label = f"{club_nom} {cat_label}".strip()
        phase_label = e.get("phase") or e.get("libellePhase") or None
        team_id = e.get("id")

        team_info = {
            "team_id": team_id,
            "engagement_id": team_id,
            "numero_equipe": numero_equipe,
            "team_label": cat_label or team_label,
            "phase_label": phase_label,
            "nom_equipe": format_team_name(club_nom, num_suffix),
            "competition": nom_comp,
            "competition_id": comp.get("id"),
            "poule_id": poule.get("id"),
            "sexe": comp.get("sexe", ""),
            "categorie": categorie_code,
            "niveau": comp.get("competition_origine_niveau"),
        }
        all_teams.append(team_info)

    # Filtrage
    if parsed_filter is None:
        return all_teams

    filtered_teams: list[dict[str, Any]] = []
    for t in all_teams:
        # Filtre catégorie (strict)
        if (
            parsed_filter.categorie
            and t["categorie"].upper() != parsed_filter.categorie.upper()
        ):
            continue
        # Filtre sexe
        if parsed_filter.sexe == "F" and (t["sexe"] or "").upper() == "M":
            continue
        if parsed_filter.sexe == "M" and (t["sexe"] or "").upper() == "F":
            continue
        filtered_teams.append(t)

    if parsed_filter.numero_equipe is not None:
        want_num = str(parsed_filter.numero_equipe)
        exact_matches = [
            t
            for t in filtered_teams
            if (t.get("numero_equipe") or "").strip() == want_num
        ]

        if exact_matches:
            filtered_teams = exact_matches
        else:
            # Fallback to teams with no explicit numero_equipe
            empty_num_matches = [
                t for t in filtered_teams if not (t.get("numero_equipe") or "").strip()
            ]
            if empty_num_matches:
                filtered_teams = empty_num_matches
                for t in filtered_teams:
                    t["note"] = (
                        "équipe sans numéro explicite, correspond potentiellement à ce numéro"
                    )
            else:
                filtered_teams = []  # No match at all

    if not filtered_teams:
        # Ambiguity Hinting: si aucun match, lister les options possibles
        suggestions = sorted(list({t["team_label"] for t in all_teams}))
        return [
            {
                "error": f"Aucune équipe matchant '{filtre}' trouvée pour '{club_nom}'.",
                "suggested_teams": suggestions,
                "hint": "Utilise l'un des labels suggérés pour une précision exacte.",
            }
        ]

    return filtered_teams


# ---------------------------------------------------------------------------
# Helpers partagés — next_match / last_result
# ---------------------------------------------------------------------------


async def _resolve_team_equipes(
    *,
    club_name: str | None,
    organisme_id: int | str | None,
    categorie: str,
    numero_equipe: int | None,
    not_found_status: str = "not_found",
) -> tuple[dict | None, list[dict], dict | None]:
    """Résout le club + filtre les équipes par catégorie/numéro.

    Returns:
        (error_response | None, equipes_filtered, club_resolu | None)
        Si error_response n'est pas None, les deux autres sont vides/None.
    """
    if not club_name and not organisme_id:
        return (
            {"status": "error", "message": "Fournir club_name ou organisme_id"},
            [],
            None,
        )

    resolved_clubs, org_data = await _resolve_club_and_org(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
    )

    if not resolved_clubs:
        return (
            {
                "status": not_found_status,
                "message": f"Club '{club_name or organisme_id}' introuvable.",
                "club_resolu": None,
            },
            [],
            None,
        )

    if len(resolved_clubs) > 1 and not organisme_id:
        return (
            {
                "status": "ambiguous",
                "message": f"Plusieurs clubs correspondent à '{club_name}'. Précisez l'organisme_id.",
                "candidates": resolved_clubs,
                "club_resolu": None,
            },
            [],
            None,
        )

    club_resolu = resolved_clubs[0]
    target_org_id = str(club_resolu["organisme_id"])

    equipes = await ffbb_equipes_club_service(
        organisme_id=target_org_id, filtre=categorie, org_data=org_data
    )

    if not equipes or (
        isinstance(equipes, list) and len(equipes) == 1 and "error" in equipes[0]
    ):
        msg = (
            equipes[0]["error"]
            if (equipes and "error" in equipes[0])
            else f"Aucune équipe trouvée pour la catégorie '{categorie}'."
        )
        suggestions = (
            equipes[0].get("suggested_teams")
            if (equipes and "suggested_teams" in equipes[0])
            else []
        )
        return (
            {
                "status": not_found_status,
                "message": msg,
                "club_resolu": club_resolu,
                "candidates": suggestions,
            },
            [],
            club_resolu,
        )

    # Filtrer par numéro d'équipe
    if numero_equipe is not None:
        want = str(numero_equipe)
        filtered = [
            e for e in equipes if (e.get("numero_equipe") or "").strip() == want
        ]
        if not filtered:
            filtered = [
                e for e in equipes if not (e.get("numero_equipe") or "").strip()
            ]
        if not filtered:
            all_available = sorted(
                list(
                    {
                        f"{e.get('team_label', categorie)} (n°{e.get('numero_equipe') or 'unique'})"
                        for e in equipes
                    }
                )
            )
            return (
                {
                    "status": not_found_status,
                    "message": f"Aucune équipe matchant '{categorie}' n°{numero_equipe} (ou unique) trouvée.",
                    "club_resolu": club_resolu,
                    "candidates": all_available,
                },
                [],
                club_resolu,
            )
        equipes = filtered

    return None, equipes, club_resolu


async def _fetch_poule_matches(
    equipes: list[dict],
    *,
    organisme_nom: str,
    numero_equipe: int | None,
    force_refresh: bool = False,
) -> list[tuple[dict, dict]]:
    """Charge les rencontres de toutes les poules en parallèle et filtre celles du club.

    Returns:
        Liste de tuples (rencontre_dict, equipe_info_dict) pour les matchs de l'équipe.
    """
    numero_equipe_match = int(numero_equipe) if numero_equipe is not None else None

    async def _fetch_one(eq: dict) -> list[tuple[dict, dict]]:
        pid = eq.get("poule_id")
        my_eng = eq.get("engagement_id")
        if not pid:
            return []
        poule = await get_poule_service(pid, force_refresh=force_refresh)
        matches: list[tuple[dict, dict]] = []
        for m in poule.get("rencontres", []) or []:
            eng1 = m.get("idEngagementEquipe1")
            eng2 = m.get("idEngagementEquipe2")
            id_eng1 = str(eng1.get("id") if isinstance(eng1, dict) else eng1)
            id_eng2 = str(eng2.get("id") if isinstance(eng2, dict) else eng2)
            str_my_eng = str(my_eng) if my_eng else None

            is_my_team = False
            if str_my_eng and (str_my_eng in (id_eng1, id_eng2)):
                is_my_team = True
            else:
                organisme_nom_norm = _normalize_name(str(organisme_nom))
                is_my_team = _match_team_name(
                    str(m.get("nomEquipe1", "")),
                    organisme_nom_norm,
                    numero_equipe_match,
                    is_organisme_nom_normalized=True,
                ) or _match_team_name(
                    str(m.get("nomEquipe2", "")),
                    organisme_nom_norm,
                    numero_equipe_match,
                    is_organisme_nom_normalized=True,
                )

            if is_my_team:
                matches.append((m, eq))
        return matches

    results = await asyncio.gather(
        *[_fetch_one(e) for e in equipes if e.get("poule_id")],
        return_exceptions=True,
    )
    all_matches: list[tuple[dict, dict]] = []
    for res in results:
        if isinstance(res, list):
            all_matches.extend(res)
    return all_matches


def _prioritize_phase(
    matches_with_eq: list[tuple[dict, dict]],
) -> list[tuple[dict, dict]]:
    """Retourne uniquement les matchs de la phase la plus élevée."""
    if not matches_with_eq:
        return []
    phase_to_matches: dict[int, list[tuple[dict, dict]]] = {}
    for m, eq in matches_with_eq:
        p_num = _extract_phase_num(eq.get("phase_label"))
        if p_num not in phase_to_matches:
            phase_to_matches[p_num] = []
        phase_to_matches[p_num].append((m, eq))
    max_phase = max(phase_to_matches.keys())
    return phase_to_matches[max_phase]


async def ffbb_next_match_service(
    *,
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str,
    numero_equipe: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Service interne pour ffbb_next_match.

    - sélectionne l'engagement correspondant à (organisme_id, categorie, numero_equipe)
    - charge la poule courante
    - retourne la prochaine rencontre non jouée.
    """
    error, equipes, club_resolu = await _resolve_team_equipes(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        numero_equipe=numero_equipe,
        not_found_status="not_found",
    )
    if error:
        return error

    poules_actives = [e["poule_id"] for e in equipes if e.get("poule_id")]
    if not poules_actives:
        all_available_equipes = sorted(
            list(
                {
                    f"{e.get('team_label', categorie)} (n°{e.get('numero_equipe') or 'unique'})"
                    for e in equipes
                }
            )
        )
        return {
            "status": "not_found",
            "message": "Aucune poule active trouvée pour cette équipe.",
            "club_resolu": club_resolu,
            "candidates": all_available_equipes,
        }

    organisme_nom = str(club_resolu.get("nom", "")) if club_resolu is not None else ""

    all_matches = await _fetch_poule_matches(
        equipes,
        organisme_nom=organisme_nom,
        numero_equipe=numero_equipe,
        force_refresh=force_refresh,
    )

    # Filtrer les matchs à venir (non joués, sans résultat)
    tz = _PARIS_TZ
    upcoming: list[tuple[datetime, dict, dict]] = []
    for m, eq in all_matches:
        joue = m.get("joue")
        res1 = m.get("resultatEquipe1", m.get("resultat_equipe1"))
        res2 = m.get("resultatEquipe2", m.get("resultat_equipe2"))
        if joue not in (0, "0", None):
            continue
        if res1 not in (None, "", "None") or res2 not in (None, "", "None"):
            continue
        dt = _parse_dt(m.get("date_rencontre", m.get("date")))
        if dt is None:
            dt = datetime.max.replace(tzinfo=tz)
        upcoming.append((dt, m, eq))

    # AUTO-REFRESH FALLBACK: Si aucun match trouvé en cache et force_refresh=False,
    # tenter un rafraîchissement pour éviter un faux "no_upcoming_match" sur cache périmé.
    if not upcoming and not force_refresh:
        logger.info(
            f"ffbb_next_match: aucun match trouvé en cache pour {categorie}, "
            "tentative de rafraîchissement..."
        )
        all_matches = await _fetch_poule_matches(
            equipes,
            organisme_nom=organisme_nom,
            numero_equipe=numero_equipe,
            force_refresh=True,
        )
        # Re-filter après refresh
        upcoming = []
        for m, eq in all_matches:
            joue = m.get("joue")
            res1 = m.get("resultatEquipe1", m.get("resultat_equipe1"))
            res2 = m.get("resultatEquipe2", m.get("resultat_equipe2"))
            if joue not in (0, "0", None):
                continue
            if res1 not in (None, "", "None") or res2 not in (None, "", "None"):
                continue
            dt = _parse_dt(m.get("date_rencontre", m.get("date")))
            if dt is None:
                dt = datetime.max.replace(tzinfo=tz)
            upcoming.append((dt, m, eq))

    if not upcoming:
        all_available_equipes = sorted(
            list(
                {
                    f"{e.get('team_label', categorie)} (n°{e.get('numero_equipe') or 'unique'})"
                    for e in equipes
                }
            )
        )
        return {
            "status": "no_upcoming_match",
            "message": "Aucun match à venir trouvé pour cette équipe.",
            "club_resolu": club_resolu,
            "candidates": all_available_equipes,
        }

    # Prioriser la phase la plus élevée
    phase_to_matches: dict[int, list[tuple[datetime, dict, dict]]] = {}
    for dt, m, eq in upcoming:
        p_num = _extract_phase_num(eq.get("phase_label"))
        if p_num not in phase_to_matches:
            phase_to_matches[p_num] = []
        phase_to_matches[p_num].append((dt, m, eq))

    max_active_phase = max(phase_to_matches.keys())
    active_phase_matches = phase_to_matches[max_active_phase]
    active_phase_matches.sort(key=lambda x: x[0])
    next_dt, next_match, source_team = active_phase_matches[0]

    eng1 = next_match.get("idEngagementEquipe1")
    eng2 = next_match.get("idEngagementEquipe2")
    id_eng1 = eng1.get("id") if isinstance(eng1, dict) else eng1
    id_eng2 = eng2.get("id") if isinstance(eng2, dict) else eng2
    my_eng = source_team.get("engagement_id")

    num1 = eng1.get("numeroEquipe") if isinstance(eng1, dict) else None
    num2 = eng2.get("numeroEquipe") if isinstance(eng2, dict) else None
    eq1_name = format_team_name(
        next_match.get("nomEquipe1", next_match.get("nom_equipe1", "")), num1
    )
    eq2_name = format_team_name(
        next_match.get("nomEquipe2", next_match.get("nom_equipe2", "")), num2
    )

    if my_eng and id_eng1 and str(my_eng) == str(id_eng1):
        adversaire = eq2_name
        domicile = True
    elif my_eng and id_eng2 and str(my_eng) == str(id_eng2):
        adversaire = eq1_name
        domicile = False
    else:
        club_nom = (source_team.get("nom_equipe") or "").lower()
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
        "club_resolu": club_resolu,
        "team": source_team,
        "match": {
            "poule_id": source_team.get("poule_id"),
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
    *,
    organisme_id: int | str,
    categorie: str,
    numero_equipe: int,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Service interne pour ffbb_bilan_saison.

    Agrège le bilan de TOUTES les phases de la saison pour une équipe précise.

    Contrairement à ffbb_bilan_service (qui part d'un club_name ou d'une
    catégorie globale), cette fonction travaille à partir d'une équipe
    identifiée sans ambiguïté.

    Args:
        force_refresh: Si True, bypass le cache pour obtenir des données fraîches.
    """
    org_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    equipes = await ffbb_equipes_club_service(
        organisme_id=org_id_int,
        filtre=categorie,
    )
    # Gestion du format d'erreur avec suggestions ( Ambiguity Hinting )
    if not equipes or (len(equipes) == 1 and "error" in equipes[0]):
        error_msg = (
            equipes[0]["error"]
            if equipes
            else f"Aucune équipe trouvée pour la catégorie '{categorie}'."
        )
        return {
            "status": "not_found",
            "message": error_msg,
            "suggestions": equipes[0].get("suggested_teams") if equipes else [],
        }

    want_num = str(numero_equipe)
    filtered_equipes = [
        e for e in equipes if (e.get("numero_equipe") or "").strip() == want_num
    ]
    if not filtered_equipes:
        # Fallback to team with empty numero_equipe (often implicitly team 1)
        filtered_equipes = [
            e for e in equipes if not (e.get("numero_equipe") or "").strip()
        ]

    if not filtered_equipes:
        return {
            "status": "not_found",
            "message": (
                "Aucune équipe ne correspond à cette combinaison "
                f"categorie={categorie!r}, numero_equipe={numero_equipe}."
            ),
        }
    equipes = filtered_equipes

    # Plusieurs phases possibles pour la même équipe : on les garde toutes.
    poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )
    if not poule_ids:
        return {
            "status": "not_found",
            "message": "Aucune poule associée à cette équipe.",
        }

    async def _fetch_poule(pid: str) -> dict[str, Any] | Exception:
        try:
            return await get_poule_service(pid, force_refresh=force_refresh)
        except Exception as e:  # déjà normalisé par get_poule_service
            return e

    poules_raw = await asyncio.gather(
        *[_fetch_poule(pid) for pid in poule_ids], return_exceptions=True
    )
    poules_map: dict[str, dict[str, Any]] = {
        pid: pd
        for pid, pd in zip(poule_ids, poules_raw, strict=False)
        if isinstance(pd, dict)
    }

    # Agrégation par phase
    phases: list[dict[str, Any]] = []
    totaux = _new_bilan_totals()

    club_nom = equipes[0].get("nom_equipe", "")

    for pid, poule_data in poules_map.items():
        classements = poule_data.get("classements", []) or []
        for entry in classements:
            eng = entry.get("id_engagement", {}) or {}
            entry_eng_id = str(eng.get("id", ""))
            if entry_eng_id not in {str(e["engagement_id"]) for e in equipes}:
                continue

            stats = _extract_and_accumulate_bilan(entry, totaux)
            phases.append(
                {
                    "competition": poule_data.get("nom", ""),
                    "poule_id": pid,
                    "position": entry.get("position"),
                    "phase_type": poule_data.get("phase_type", "poule"),
                    "phase_terminee": poule_data.get("phase_terminee", False),
                    **stats,
                }
            )

    phases.sort(key=lambda x: x["competition"])

    return {
        "status": "ok",
        "club": club_nom,
        "categorie": categorie or "",
        "bilan_total": totaux,
        "phases": phases,
        "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
    }


async def ffbb_bilan_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Bilan complet d'une équipe toutes phases confondues en un seul appel.
    Workflow interne : search → equipes → poules (parallèle) → agrégation V/D/N + paniers.

    Args:
        force_refresh: Si True, bypass le cache pour obtenir des données fraîches.
    """
    cache_key = f"bilan:{organisme_id or ''}:{_normalize_name(club_name or '')}:{_normalize_name(categorie or '')}"

    async def _fetch() -> dict[str, Any]:
        # 1. Résoudre l'organisme_id (CENTRALISÉ)
        resolved_clubs, org_data = await _resolve_club_and_org(
            club_name=club_name, organisme_id=organisme_id, categorie=categorie
        )
        target_org_ids = [str(c["organisme_id"]) for c in resolved_clubs]
        club_nom = resolved_clubs[0]["nom"] if resolved_clubs else (club_name or "")

        if not target_org_ids:
            return {
                "error": f"Club '{club_name}' introuvable",
                "suggestion": "Vérifiez l'orthographe ou résolvez d'abord le club avec ffbb_search.",
                "next_call": f"ffbb_search(type='organismes', query='{club_name or ''}')",
                "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
            }

        # 2. Récupérer les équipes filtrées en parallèle
        eq_tasks = []
        for oid in target_org_ids:
            # On passe org_data seulement si c'est l'organisme cible direct
            # pour optimiser l'appel interne.
            is_target = organisme_id and str(oid) == str(organisme_id)
            pass_org = org_data if is_target else None
            eq_tasks.append(
                ffbb_equipes_club_service(
                    organisme_id=oid, filtre=categorie, org_data=pass_org
                )
            )
        eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

        equipes: list[dict[str, Any]] = []
        for res in eq_results:
            if isinstance(res, list):
                # FILTRE: on ignore les dictionnaires d'erreur (Hinting) pour le traitement interne
                equipes.extend(
                    [e for e in res if isinstance(e, dict) and "error" not in e]
                )
            elif isinstance(res, Exception):
                logger.error("Erreur lors de la récupération des équipes: %s", res)

        if not equipes:
            return {
                "error": f"Aucune équipe trouvée pour la catégorie '{categorie}'",
                "suggestion": "Listez les équipes disponibles puis choisissez la catégorie et le numéro exacts.",
                "next_call": (
                    f"ffbb_club(action='equipes', organisme_id={target_org_ids[0]})"
                    if target_org_ids
                    else "ffbb_club(action='equipes', club_name='<club>')"
                ),
                "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
            }

        equipes = _dedup_equipes_by_engagement(equipes)

        # 3. Récupérer toutes les poules concernées
        unique_poule_ids = list(
            dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
        )
        # FIX: print() → logger.debug() (les print polluaient stdout/Coolify en prod)
        logger.debug(f"ffbb_bilan: club_nom={club_nom} cible_orgs={target_org_ids}")
        logger.debug(
            f"ffbb_bilan: equipes_count={len(equipes)} unique_poules={unique_poule_ids}"
        )

        async def _fetch_poule_bilan(pid: str) -> dict[str, Any] | Exception:
            try:
                return await get_poule_service(pid)
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
            if isinstance(pd, dict)
        }
        logger.debug("ffbb_bilan: poules_map_keys=%s", list(poules_map.keys()))

        # Map poule_id → engagement_ids du club + nom compétition + numero_equipe
        poule_to_eng: dict[str, set[str]] = {}
        poule_to_comp: dict[str, str] = {}
        eng_to_num: dict[str, str] = {}  # engagement_id → numero_equipe
        org_ids_str = set(target_org_ids)
        for e in equipes:
            pid = str(e.get("poule_id", ""))
            eid = str(e.get("engagement_id", ""))
            num = str(e.get("numero_equipe") or "")
            if pid and eid:
                poule_to_eng.setdefault(pid, set()).add(eid)
                if num:
                    eng_to_num[eid] = num
            if pid and e.get("competition"):
                poule_to_comp[pid] = e["competition"]

        # 4. Agréger par phase
        phases: list[dict[str, Any]] = []
        totaux = _new_bilan_totals()

        for pid, poule_data in poules_map.items():
            if not isinstance(poule_data, dict):
                continue
            eng_ids_here = poule_to_eng.get(pid, set())
            for entry in poule_data.get("classements", []) or []:
                if not isinstance(entry, dict):
                    continue
                eng = entry.get("id_engagement", {}) or {}
                entry_eng_id = str(eng.get("id", ""))
                entry_org_id = str(entry.get("organisme_id", ""))

                if entry_eng_id in eng_ids_here:
                    pass
                elif entry_org_id in org_ids_str:
                    logger.debug(
                        "ffbb_bilan: fallback org_id utilisé pour entry_eng_id=%s org_id=%s",
                        entry_eng_id,
                        entry_org_id,
                    )
                else:
                    continue

                stats = _extract_and_accumulate_bilan(entry, totaux)

                # Résolution du numéro d'équipe : priorité au mapping issu de
                # ffbb_equipes_club_service (le plus fiable), sinon lecture directe
                # dans l'entrée de classement retournée par l'API (fallback propre).
                num_equipe = eng_to_num.get(entry_eng_id) or str(
                    eng.get("numero_equipe") or ""
                )

                phases.append(
                    {
                        "competition": poule_to_comp.get(pid, ""),
                        "poule_id": pid,
                        "numero_equipe": num_equipe,
                        "position": entry.get("position"),
                        "phase_type": poule_data.get("phase_type", "poule"),
                        "phase_terminee": poule_data.get("phase_terminee", False),
                        **stats,
                    }
                )

        # Tri déterministe : par compétition puis par numéro d'équipe pour que
        # les phases d'une même équipe soient toujours regroupées dans l'ordre.
        phases.sort(key=lambda x: (x["competition"], x["numero_equipe"] or ""))

        # Structure groupée par numéro d'équipe pour éliminer toute ambiguïté
        # lorsqu'un club engage plusieurs équipes dans la même catégorie.
        equipes_bilan: dict[str, Any] = {}
        for p in phases:
            num = p["numero_equipe"] or "1"
            if num not in equipes_bilan:
                equipes_bilan[num] = {
                    "numero_equipe": num,
                    "bilan": _new_bilan_totals(),
                    "phases": [],
                }
            equipes_bilan[num]["phases"].append(p)
            b = equipes_bilan[num]["bilan"]
            for f in _BILAN_STAT_FIELDS:
                b[f] += p[f]

        # Identifier la phase la plus récente pour l'équipe principale
        phase_courante = None
        if phases:
            target_phases = [
                p for p in phases if str(p.get("numero_equipe", "1")) == "1"
            ]
            phase_courante = target_phases[-1] if target_phases else phases[-1]

        return {
            "club": club_nom,
            "categorie": categorie or "",
            "bilan_total": totaux,
            "phase_courante": phase_courante,
            "equipes_bilan": equipes_bilan,
            "phases": phases,
            "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
        }

    # Force refresh : bypass le cache et appel direct
    if force_refresh and state.cache_bilan is not None:
        logger.debug(f"force_refresh=True, bypass cache pour {cache_key}")
        state.cache_bilan.pop(cache_key, None)

    return await _dedupe_inflight(
        cache=state.cache_bilan,
        cache_key=cache_key,
        inflight_map=state.inflight_bilan,
        make_coro=_fetch,
        cache_name="bilan",
    )


async def get_calendrier_club_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    numero_equipe: int | None = None,
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
    cache_key = f"calendrier:{organisme_id or ''}:{_normalize_name(club_name or '')}:{_normalize_name(categorie or '')}:{numero_equipe or ''}"

    async def _fetch() -> list[dict]:
        # 1. Résoudre les organismes cibles (CENTRALISÉ)
        resolved_clubs, _ = await _resolve_club_and_org(
            club_name=club_name, organisme_id=organisme_id, categorie=categorie, limit=5
        )
        target_org_ids = [str(c["organisme_id"]) for c in resolved_clubs]

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
                # FILTRE: on ignore les dictionnaires d'erreur (Hinting) pour le traitement interne
                equipes.extend(
                    [e for e in res if isinstance(e, dict) and "error" not in e]
                )
            elif isinstance(res, Exception):
                logger.error("Erreur lors de la récupération des équipes: %s", res)

        # Filtrage par numero_equipe si fourni
        if numero_equipe is not None:
            equipes = [
                e
                for e in equipes
                if str(e.get("numero_equipe", "")) == str(numero_equipe)
                or str(e.get("nom", "")).endswith(f"- {numero_equipe}")
                or f" - {numero_equipe} " in str(e.get("nom", ""))
                or f"-{numero_equipe} " in str(e.get("nom", ""))
            ]

        if not equipes:
            return []

        # Dédupliquer les équipes par engagement_id pour éviter les doublons de matchs
        equipes = _dedup_equipes_by_engagement(equipes)

        # 3. Parcourir toutes les poules de ces équipes pour récupérer toutes les rencontres et scores
        seen_match_ids: set[Any] = set()
        all_matches: list[dict[str, Any]] = []

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
                not isinstance(poule_data, dict)
                or not poule_data
                or "rencontres" not in poule_data
            ):
                continue

            for match in poule_data.get("rencontres", []) or []:
                if not isinstance(match, dict):
                    continue
                match_id = match.get("id")
                if not match_id or match_id in seen_match_ids:
                    continue

                # La poule est déjà scopée à l'engagement du club :
                # on ne charge que les poules où il est inscrit.
                # Pas besoin de refiltrer par engagement_id/nom_equipe —
                # ce filtre supprimait silencieusement tous les matchs
                # car les IDs dans les rencontres (idEngagementEquipe1/2)
                # ne correspondent pas à l'ID d'engagement de l'organisme.
                # Seule la déduplication par match_id est nécessaire.
                seen_match_ids.add(match_id)

                eng1 = match.get("idEngagementEquipe1")
                eng2 = match.get("idEngagementEquipe2")
                num1 = eng1.get("numeroEquipe") if isinstance(eng1, dict) else None
                num2 = eng2.get("numeroEquipe") if isinstance(eng2, dict) else None

                eq1 = format_team_name(
                    match.get("nomEquipe1", match.get("nom_equipe1", "")), num1
                )
                eq2 = format_team_name(
                    match.get("nomEquipe2", match.get("nom_equipe2", "")), num2
                )
                score1 = match.get("resultatEquipe1", match.get("resultat_equipe1"))
                score2 = match.get("resultatEquipe2", match.get("resultat_equipe2"))
                date_match = match.get("date_rencontre", match.get("date", ""))
                journee = match.get("numeroJournee", match.get("numero_journee", ""))
                joue = match.get("joue")
                salle = (
                    match.get("salle") or match.get("idSalle") or match.get("id_salle")
                )

                calendar_match = {
                    "id": match_id,
                    "date": date_match,
                    "joue": joue,
                    "equipe1": eq1,
                    "equipe2": eq2,
                    "score_equipe1": score1,
                    "score_equipe2": score2,
                    "competition_nom": equipe.get("competition", ""),
                    "num_journee": journee,
                }
                if salle:
                    calendar_match["salle"] = salle
                all_matches.append(calendar_match)

        await _enrich_matches_with_salle_details(all_matches)

        # --- Tri robuste par date + flags temporels ---
        tz = _PARIS_TZ
        now = datetime.now(tz)

        # Attacher un datetime parsé temporaire pour le tri
        for m in all_matches:
            m["_dt"] = _parse_dt(m.get("date"))

        # Tri décroissant: du plus récent au plus ancien. Si la date manque, on met en fin.
        all_matches.sort(
            key=lambda x: (x["_dt"] is None, x["_dt"] or now), reverse=True
        )

        # Déterminer played / futur
        played_indices: list[int] = []
        future_indices: list[int] = []

        for idx, m in enumerate(all_matches):
            m["played"] = (
                m.get("joue") == 1 or m.get("joue") == "1" or m.get("joue") is True
            )
            if m["played"]:
                played_indices.append(idx)
            else:
                future_indices.append(idx)

        last_played_idx = played_indices[0] if played_indices else None
        next_future_idx = future_indices[-1] if future_indices else None

        for idx, m in enumerate(all_matches):
            m["is_last_match"] = last_played_idx is not None and idx == last_played_idx
            m["is_next_match"] = next_future_idx is not None and idx == next_future_idx
            m.pop("_dt", None)

        effective = all_matches

        if len(effective) > _MAX_CALENDAR_MATCHES:
            truncated = effective[:_MAX_CALENDAR_MATCHES]
            warning = {
                "warning": (
                    "Résultat tronqué côté MCP: trop de matchs pour ce club/catégorie. "
                    "Affichage limité pour protéger les performances. "
                    "Affinez votre requête (catégorie précise, équipe 1/2, phase, etc.)."
                ),
                "total_initial": len(all_matches),
                "limite_appliquee": _MAX_CALENDAR_MATCHES,
            }
            truncated.append(warning)
            return truncated

        return effective

    # force_refresh contourne le cache de calendrier, mais continue de bénéficier
    # de la déduplication inflight.
    if force_refresh and state.cache_calendrier is not None:
        state.cache_calendrier.pop(cache_key, None)

    return await _dedupe_inflight(
        cache=state.cache_calendrier,
        cache_key=cache_key,
        inflight_map=state.inflight_calendrier,
        make_coro=_fetch,
        cache_name="calendrier",
    )


async def search_organismes_service(
    nom: str,
    limit: int = 20,
    filter_by: str | None = None,
    sort: list[str] | None = None,
) -> list[dict]:
    return await _search_generic(
        "organismes", "search_organismes_async", nom, limit, filter_by, sort
    )


# Mapping de configuration pour les types de recherche non exposés individuellement.
_SEARCH_TYPE_METHOD: dict[str, str] = {
    "competitions": "search_competitions_async",
    "salles": "search_salles_async",
    "rencontres": "search_rencontres_async",
    "pratiques": "search_pratiques_async",
    "terrains": "search_terrains_async",
    "tournois": "search_tournois_async",
    "engagements": "search_engagements_async",
    "formations": "search_formations_async",
    "officiels": "search_officiels_async",
    "entraineurs": "search_entraineurs_async",
    "communes": "search_communes_async",
}


async def get_rencontre_service(rencontre_id: int | str) -> dict[str, Any]:
    client = await get_client_async()
    result = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            f"Get rencontre {rencontre_id}",
            lambda: client.get_rencontre_async(str(rencontre_id)),
        )
    )
    data = serialize_model(result) if result is not None else {}
    return (
        await _enrich_with_salle_details(data, client) if isinstance(data, dict) else {}
    )


async def get_officiel_service(officiel_id: int | str) -> dict[str, Any]:
    client = await get_client_async()
    result = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            f"Get officiel {officiel_id}",
            lambda: client.get_officiel_async(str(officiel_id)),
        )
    )
    return serialize_model(result) if result is not None else {}


async def get_entraineur_service(entraineur_id: int | str) -> dict[str, Any]:
    client = await get_client_async()
    result = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            f"Get entraineur {entraineur_id}",
            lambda: client.get_entraineur_async(str(entraineur_id)),
        )
    )
    return serialize_model(result) if result is not None else {}


async def ffbb_search_service(
    *,
    type: str = "all",
    query: str,
    limit: int = 20,
    filter_by: str | None = None,
    sort: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Service de recherche FFBB.

    Recherche dans les données FFBB en fonction de plusieurs types de données.
    """
    # type == "all" → multi_search dédiée
    if type == "all":
        return await multi_search_service(nom=query, limit=limit)

    # organismes → fonction dédiée (importée ailleurs)
    if type == "organismes":
        return await search_organismes_service(query, limit, filter_by, sort)

    # Autres types → appel direct via le mapping de configuration
    if method_name := _SEARCH_TYPE_METHOD.get(type):
        return await _search_generic(type, method_name, query, limit, filter_by, sort)

    raise McpError(
        error=ErrorData(
            code=INTERNAL_ERROR,
            message=f"Type de recherche inconnu: {type}",
        )
    )


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

    # 1) Résoudre l'organisme avec métadonnées (CENTRALISÉ)
    resolved_clubs, _ = await _resolve_club_and_org(
        club_name=club_name, organisme_id=organisme_id, categorie=categorie
    )

    if not resolved_clubs:
        return {
            "status": "not_found",
            "team": None,
            "candidates": [],
            "ambiguity": f"Club '{club_name or organisme_id}' introuvable",
            "club_resolu": None,
        }

    # Si ambiguïté club
    if len(resolved_clubs) > 1 and not organisme_id:
        return {
            "status": "ambiguous",
            "team": None,
            "candidates": resolved_clubs,
            "ambiguity": f"Plusieurs clubs correspondent à '{club_name}'.",
            "club_resolu": None,
        }

    club_resolu = resolved_clubs[0]
    target_org_id = str(club_resolu["organisme_id"])

    # 2) Récupérer toutes les équipes candidates
    equipes = await ffbb_equipes_club_service(
        organisme_id=target_org_id, filtre=categorie
    )

    if not equipes or (
        isinstance(equipes, list) and len(equipes) == 1 and "error" in equipes[0]
    ):
        msg = (
            equipes[0]["error"]
            if (equipes and "error" in equipes[0])
            else f"Aucune équipe trouvée pour la catégorie '{categorie}'."
        )
        suggestions = (
            equipes[0].get("suggested_teams")
            if (equipes and "suggested_teams" in equipes[0])
            else []
        )
        return {
            "status": "not_found",
            "team": None,
            "candidates": suggestions,
            "ambiguity": msg,
            "club_resolu": club_resolu,
        }

    # 3) Matching intelligent du numéro (LOGIQUE CORRIGÉE)
    candidates = equipes
    parsed = parse_categorie(categorie)
    target_num = str(parsed.numero_equipe) if parsed.numero_equipe else None

    # On cherche d'abord le numéro exact
    if target_num:
        matched = [
            e
            for e in candidates
            if (e.get("numero_equipe") or "").strip() == target_num
        ]
        if not matched:
            # Fallback sur équipe sans numéro
            matched = [
                e for e in candidates if not (e.get("numero_equipe") or "").strip()
            ]
        if matched:
            candidates = matched

    # 4) Construire la réponse
    if not candidates:
        all_labels = sorted(list({t["team_label"] for t in equipes}))
        return {
            "status": "not_found",
            "team": None,
            "candidates": all_labels,
            "ambiguity": f"Aucun match exact pour '{categorie}'",
            "club_resolu": club_resolu,
        }

    if len(candidates) == 1:
        return {
            "status": "resolved",
            "team": candidates[0],
            "candidates": candidates,
            "ambiguity": None,
            "club_resolu": club_resolu,
        }

    # Si on a plusieurs candidats, on vérifie s'ils partagent tous le même numero_equipe.
    # Si c'est le cas, ce ne sont que des phases successives (Phase 1, 2, 3...)
    # de la même équipe réelle au sein du club résolu.
    unique_nums = {str(c.get("numero_equipe") or "").strip() for c in candidates}

    if len(unique_nums) == 1:
        # Trier par niveau pour prendre la phase la plus récente/haute (si dispo)
        # ou simplement prendre la dernière de la liste qui est souvent chronologique.
        # Par sécurité on prend la dernière:
        return {
            "status": "resolved",
            "team": candidates[-1],
            "candidates": candidates,
            "ambiguity": None,
            "club_resolu": club_resolu,
        }

    return {
        "status": "ambiguous",
        "team": None,
        "candidates": candidates,
        "ambiguity": f"Plusieurs équipes ({len(candidates)}) correspondent à '{categorie}'.",
        "club_resolu": club_resolu,
    }


# --- Helpers d'identification d'equipe --------------------------------------

# Mots génériques qui n'identifient pas un club de manière distinctive.
_GENERIC_CLUB_WORDS: frozenset[str] = frozenset(
    [
        "BASKET",
        "BASKETBALL",
        "BALL",
        "CLUB",
        "BC",
        "BBC",
        "ABC",
        "BB",
        "CB",
        "SB",
        "JS",
        "AC",
        "AS",
        "US",
        "FC",
        "UNION",
        "ASSOCIATION",
        "SPORTING",
        "SPORT",
        "SPORTS",
        "GARDE",
        "ENTENTE",
    ]
)


@lru_cache(maxsize=512)
def _extract_club_key_word(club_name: str) -> str | None:
    """Extrait le mot distinctif d'un nom de club en supprimant les termes génériques.

    Exemple : 'Gerzat Basket' → 'GERZAT', 'BC Clermont' → 'CLERMONT'.
    Retourne None si aucun mot distinctif d'au moins 4 caractères n'est trouvé,
    ou si le mot distinctif coïncide avec le nom normalisé complet (aucun apport).
    """
    norm = _normalize_name(club_name)
    words = norm.split()
    key_words = [w for w in words if w not in _GENERIC_CLUB_WORDS and len(w) >= 4]
    if not key_words:
        return None
    candidate = key_words[0]
    # Inutile de chercher si le mot-clé représente déjà toute la requête normalisée
    if candidate == norm:
        return None
    return candidate


@lru_cache(maxsize=512)
def _normalize_name(value: str) -> str:
    """Normalise un nom (strip, upper, supprime les accents sans perdre de caractères)."""
    if not value:
        return ""
    s = value.strip().upper()

    # ⚡ Bolt: Fast-path pour les chaînes déjà ASCII (sans accents ni caractères spéciaux).
    # Évite l'overhead de la normalisation Unicode et de l'itération lettre par lettre
    # qui est ~1.4x plus lente.
    if s.isascii():
        return s

    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) not in ("Mn", "So"))


async def _resolve_club_and_org(
    club_name: str | None,
    organisme_id: int | str | None,
    categorie: str | None = None,
    limit: int = 5,
) -> tuple[list[dict[str, Any]], dict | None]:
    """Centralise la résolution d'un club vers une liste d'organismes candidats.
    Retourne (candidats, premier_org_data).

    Si categorie est fournie, applique une logique de filtrage M/F (Règle 10).
    """
    resolved = []
    org_data = None

    if organisme_id is not None:
        try:
            org_info = await get_organisme_service(str(organisme_id))
            if org_info and isinstance(org_info, dict):
                org_data = org_info
                resolved.append(
                    {
                        "nom": org_info.get("nom", ""),
                        "organisme_id": org_info.get("id") or organisme_id,
                        "code": org_info.get("code", ""),
                    }
                )
        except Exception:
            logger.debug(
                "Impossible de charger l'organisme_id %s",
                organisme_id,
                exc_info=True,
            )
    elif club_name:
        # Recherche secondaire parallèle pour les ententes (ENT. CLUB_A / CLUB_B).
        # Une entente est un organisme distinct dont le nom commence par "ENT." et
        # contient le mot distinctif du club (ex: "Gerzat Basket" → "GERZAT").
        key_word = _extract_club_key_word(club_name)
        search_tasks: list[Any] = [
            search_organismes_service(nom=club_name, limit=limit)
        ]
        if key_word:
            search_tasks.append(
                search_organismes_service(nom=key_word, limit=limit + 5)
            )
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        orgs: list[dict] = (
            search_results[0] if isinstance(search_results[0], list) else []
        )
        ent_orgs_raw: list[dict] = (
            search_results[1]
            if len(search_tasks) > 1 and isinstance(search_results[1], list)
            else []
        )

        # Application de la Règle 10 (Smart Resolution M/F)
        if len(orgs) > 1 and categorie:
            parsed = parse_categorie(categorie)
            gender = parsed.sexe  # 'M' or 'F' or None

            # Si le nom fourni contient déjà "FEMININ", on ne filtre pas (choix explicite)
            name_norm = _normalize_name(club_name)
            is_explicit_fem = "FEMININ" in name_norm

            if gender and not is_explicit_fem:
                fem_orgs = [
                    o
                    for o in orgs
                    if "FEMININ" in _normalize_name(str(o.get("nom", "")))
                ]
                gen_orgs = [
                    o
                    for o in orgs
                    if "FEMININ" not in _normalize_name(str(o.get("nom", "")))
                ]

                if gender == "F" and fem_orgs:
                    orgs = fem_orgs  # On priorise les clubs féminins
                elif gender == "M" and gen_orgs:
                    orgs = gen_orgs  # On priorise les clubs généraux/masculins

        if orgs:
            # On récupère le détail du premier pour avoir les métadonnées riches
            try:
                first_org_id = orgs[0].get("id")
                if first_org_id:
                    org_data = await get_organisme_service(first_org_id)
            except Exception:
                logger.debug(
                    "Impossible de charger les détails du premier organisme pour %s",
                    club_name,
                    exc_info=True,
                )

        for org in orgs:
            if isinstance(org, dict) and org.get("id"):
                nom = org.get("nom", "")
                resolved.append(
                    {
                        "nom": nom,
                        "organisme_id": org.get("id"),
                        "code": org.get("code", ""),
                    }
                )
                # Enrichissement auto du cache d'acronymes
                if nom:
                    enrich_acronym_cache(nom)

        # Ajout des ententes associées issues de la recherche secondaire.
        if key_word and ent_orgs_raw:
            existing_ids = {str(r["organisme_id"]) for r in resolved}
            key_word_norm = _normalize_name(key_word)
            for ent_org in ent_orgs_raw:
                if not isinstance(ent_org, dict):
                    continue
                oid = str(ent_org.get("id", ""))
                if not oid or oid in existing_ids:
                    continue
                nom_norm = _normalize_name(str(ent_org.get("nom", "")))
                # Inclure uniquement les ententes (nom commençant par "ENT.")
                # qui contiennent le mot-clé distinctif du club recherché.
                is_entente = nom_norm.startswith("ENT.") or nom_norm.startswith("ENT ")
                if is_entente and key_word_norm in nom_norm:
                    nom = ent_org.get("nom", "")
                    resolved.append(
                        {
                            "nom": nom,
                            "organisme_id": oid,
                            "code": ent_org.get("code", ""),
                        }
                    )
                    existing_ids.add(oid)
                    logger.debug(
                        "ffbb_resolve: entente détectée '%s' (id=%s) pour club_name='%s'",
                        nom,
                        oid,
                        club_name,
                    )

    return resolved, org_data


@lru_cache(maxsize=256)
def _match_team_name(
    nom_equipe_rencontre: str,
    organisme_nom: str,
    numero_equipe: int | None,
    is_organisme_nom_normalized: bool = False,
) -> bool:
    """Retourne True si nom_equipe_rencontre correspond a l'equipe du club.

    Regles :
      - on normalise les chaines (strip, upper, sans accents),
      - on verifie que le nom du club est contenu,
      - si numero_equipe est None ou 1, on accepte un suffixe absent ou "- 1",
      - sinon on exige le suffixe exact "- {numero_equipe}".
    """

    nom_norm = _normalize_name(nom_equipe_rencontre)
    club_norm = (
        organisme_nom if is_organisme_nom_normalized else _normalize_name(organisme_nom)
    )
    if not nom_norm or not club_norm:
        return False
    if club_norm not in nom_norm:
        return False

    # On traite None comme 1 pour la recherche de suffixe (équipe unique ou principale)
    search_num = numero_equipe if numero_equipe is not None else 1
    suffix = f"- {search_num}"
    suffix_norm = _normalize_name(suffix)

    if search_num == 1:
        # Equipe unique : suffixe optionnel.
        # On accepte soit le suffixe "- 1", soit l'absence de chiffre dans le nom.
        # ⚡ Bolt: Remplacement de any(ch.isdigit()) par la regex compilée en C
        # pour éviter l'overhead de la boucle et du générateur Python.
        has_digit = bool(_NUMERIC_EXTRACT_PATTERN.search(nom_norm))
        return nom_norm.endswith(suffix_norm) or not has_digit

    return nom_norm.endswith(suffix_norm)


async def resolve_poule_id_service(
    organisme_id: int | str,
    categorie: str,
    phase_query: str | None = None,
) -> str | None:
    """Résout le poule_id d'une équipe pour une phase donnée (ex: 'phase 3').

    Si phase_query est None, retourne le poule_id de l'engagement le plus récent
    (plus haut niveau ou phase chronologique la plus avancée).
    """
    org_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    equipes = await ffbb_equipes_club_service(organisme_id=org_id_int, filtre=categorie)
    if not equipes:
        return None

    # Si une phase est spécifiée (ex: "phase 3", "3", "p3")
    if phase_query:
        target_phase = phase_query.strip()
        phase_num_match = _NUMERIC_EXTRACT_PATTERN.search(target_phase)
        target_phase_int: int | None = (
            int(phase_num_match.group(1)) if phase_num_match else None
        )

        for e in equipes:
            if target_phase_int is not None:
                # Comparaison par numéro entier extrait via _extract_phase_num.
                # Évite le faux-positif de "3" in "u13f phase 1" (bug sous-chaîne).
                phase_in_label = _extract_phase_num(e.get("phase_label"))
                phase_in_comp = _extract_phase_num(e.get("competition"))
                if (
                    phase_in_label == target_phase_int
                    or phase_in_comp == target_phase_int
                ):
                    return str(e.get("poule_id"))
            else:
                # Requête non numérique : matching texte uniquement dans phase_label
                phase_label = (e.get("phase_label") or "").lower()
                if target_phase.lower() in phase_label:
                    return str(e.get("poule_id"))

        # Phase explicitement demandée mais non trouvée → ne pas silencieusement
        # sélectionner la mauvaise poule via le tri par défaut : retourner None.
        return None

    # Par défaut (no phase_query), on prend l'engagement avec la phase la plus avancée.
    # On utilise _extract_phase_num pour éviter de confondre le numéro de catégorie
    # (ex: 13 dans U13F) avec un numéro de phase.
    def sort_key(e: dict) -> tuple[int, int]:
        phase_num = _extract_phase_num(e.get("phase_label") or e.get("competition"))
        return (phase_num, e.get("niveau") or 0)

    equipes.sort(key=sort_key, reverse=True)
    return str(equipes[0].get("poule_id"))


async def ffbb_last_result_service(
    *,
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str,
    numero_equipe: int = 1,
    force_refresh: bool = False,
) -> dict:
    error, equipes, club_resolu = await _resolve_team_equipes(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        numero_equipe=numero_equipe,
        not_found_status="no_result",
    )
    if error:
        return error

    organisme_nom = str(club_resolu.get("nom", "")) if club_resolu is not None else ""

    async def _get_latest_match(refresh: bool) -> dict[str, Any] | None:
        all_matches = await _fetch_poule_matches(
            equipes,
            organisme_nom=organisme_nom,
            numero_equipe=numero_equipe,
            force_refresh=refresh,
        )
        # Filtrer les matchs joués avec résultat
        joues = [
            (m, eq)
            for m, eq in all_matches
            if m.get("joue") == 1 and m.get("resultatEquipe1") not in (None, "None")
        ]
        if not joues:
            return None

        # Prioriser la phase la plus élevée
        active_phase = _prioritize_phase(joues)
        # Trier par date desc pour prendre le plus récent
        active_phase.sort(
            key=lambda x: (
                _parse_dt(x[0].get("date_rencontre", "") or "")
                or datetime.min.replace(tzinfo=_PARIS_TZ)
            ),
            reverse=True,
        )
        return active_phase[0][0]

    # 1. Premier appel
    dernier: dict[str, Any] | None = await _get_latest_match(force_refresh)

    # 2. Check 30 days — auto-refresh si dernier match trop ancien
    if dernier and not force_refresh:
        date_str = dernier.get("date_rencontre", "")
        if len(date_str) >= 10:
            seuil_str = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            if date_str[:10] < seuil_str:
                logger.info(
                    f"ffbb_last_result: match > 30 jours ({date_str[:10]} < {seuil_str}), force_refresh déclenché."
                )
                dernier_refresh = await _get_latest_match(True)
                if dernier_refresh:
                    dernier = dernier_refresh

    if not dernier:
        all_available_equipes = sorted(
            list(
                {
                    f"{e.get('team_label', categorie)} (n°{e.get('numero_equipe') or 'unique'})"
                    for e in equipes
                }
            )
        )
        return {
            "status": "no_result",
            "message": "Aucun match joué trouvé.",
            "club_resolu": club_resolu,
            "candidates": all_available_equipes,
            "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
        }

    _numero_equipe_match = int(numero_equipe) if numero_equipe is not None else None
    est_domicile = _match_team_name(
        str(dernier.get("nomEquipe1", "")), str(organisme_nom), _numero_equipe_match
    )

    def _safe_int(val: Any) -> int | None:
        if val is None or val in ("", "None"):
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    score_nous_raw = (
        dernier["resultatEquipe1"] if est_domicile else dernier["resultatEquipe2"]
    )
    score_eux_raw = (
        dernier["resultatEquipe2"] if est_domicile else dernier["resultatEquipe1"]
    )
    score_nous = _safe_int(score_nous_raw)
    score_eux = _safe_int(score_eux_raw)
    victoire = (
        score_nous is not None and score_eux is not None and score_nous > score_eux
    )

    eng1 = dernier.get("idEngagementEquipe1")
    eng2 = dernier.get("idEngagementEquipe2")
    num1 = eng1.get("numeroEquipe") if isinstance(eng1, dict) else None
    num2 = eng2.get("numeroEquipe") if isinstance(eng2, dict) else None

    return {
        "status": "ok",
        "club_resolu": club_resolu,
        "date": dernier.get("date_rencontre", ""),
        "journee": dernier.get("numeroJournee"),
        "domicile": format_team_name(dernier.get("nomEquipe1", ""), num1),
        "score_domicile": dernier.get("resultatEquipe1"),
        "exterieur": format_team_name(dernier.get("nomEquipe2", ""), num2),
        "score_exterieur": dernier.get("resultatEquipe2"),
        "victoire": victoire,
        "_meta": _freshness_meta(cache="poule", force_refresh_supported=True),
    }
