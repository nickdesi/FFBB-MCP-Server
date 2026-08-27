from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio


def _read_positive_int_env(key: str, default: int) -> int:
    val_str = os.environ.get(key)
    if val_str is not None:
        try:
            val = int(val_str)
            if val > 0:
                return val
        except ValueError:
            pass
    return default


@dataclass
class _ServiceState:
    inflight_bilan: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_calendrier: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_poule: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_classement: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_detail: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_search: dict[str, asyncio.Task[Any]] = field(default_factory=dict)

    # Stale-While-Revalidate : horodatage du dernier fetch et tâches de refresh
    swr_last_fetch: dict[str, float] = field(default_factory=dict)
    swr_tasks: dict[str, asyncio.Task[Any]] = field(default_factory=dict)

    # Caches in-memory globaux
    cache_lives: Any = None
    cache_search: Any = None
    cache_competition: Any = None
    cache_organisme: Any = None
    cache_saisons: Any = None
    cache_calendrier: Any = None
    cache_bilan: Any = None
    cache_classement: Any = None
    cache_poule: Any = None
    cache_salle: Any = None
    cache_resolve_club: Any = None
    cache_equipes: Any = None

    # Registre dynamique et auto-guérissable des index Meilisearch
    active_search_indexes: list[str] | None = None


state = _ServiceState()


def _reset_cache(cache: Any) -> None:
    if cache is None:
        return
    cache.clear()
    # Vide aussi le backing SQLite si le cache est persistant, pour garantir
    # l'isolation entre tests (sinon les entrées disque survivent au clear mémoire).
    clear_db = getattr(cache, "clear_db", None)
    if callable(clear_db):
        with contextlib.suppress(Exception):
            clear_db()


def reset_service_state() -> None:
    global state
    state.inflight_bilan.clear()
    state.inflight_calendrier.clear()
    state.inflight_poule.clear()
    state.inflight_detail.clear()
    state.inflight_classement.clear()
    state.inflight_search.clear()
    state.swr_last_fetch.clear()
    state.swr_tasks.clear()
    _reset_cache(state.cache_lives)
    _reset_cache(state.cache_search)
    _reset_cache(state.cache_competition)
    _reset_cache(state.cache_organisme)
    _reset_cache(state.cache_saisons)
    _reset_cache(state.cache_calendrier)
    _reset_cache(state.cache_bilan)
    _reset_cache(state.cache_classement)
    _reset_cache(state.cache_poule)
    _reset_cache(state.cache_salle)
    _reset_cache(state.cache_resolve_club)
    _reset_cache(state.cache_equipes)
    state.active_search_indexes = None
    _clear_lru_caches()


def _clear_lru_caches() -> None:
    """Vide les caches LRU Python des helpers utils/services (parse_categorie, etc.)."""
    try:
        from ffbb_mcp.utils import parse_categorie

        parse_categorie.cache_clear()
    except ImportError, AttributeError:
        pass
    try:
        from ffbb_mcp.services.common import _normalize_name

        _normalize_name.cache_clear()
    except ImportError, AttributeError:
        pass
