import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from cachetools import TLRUCache, TTLCache


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
    inflight_search_club: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_search_org: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_bilan: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_calendrier: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_lives: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_saisons: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_poule: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_detail: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_search: dict[str, asyncio.Task[Any]] = field(default_factory=dict)

    # Caches in-memory globaux
    cache_lives: TTLCache[Any, Any] | None = None
    cache_search: TTLCache[Any, Any] | None = None
    cache_detail: TTLCache[Any, Any] | None = None
    cache_calendrier: TTLCache[Any, Any] | None = None
    cache_bilan: TLRUCache[Any, Any] | None = None
    cache_classement: TLRUCache[Any, Any] | None = None
    cache_poule: TLRUCache[Any, Any] | None = None


state = _ServiceState()


def reset_service_state() -> None:
    global state
    state.inflight_search_club.clear()
    state.inflight_search_org.clear()
    state.inflight_bilan.clear()
    state.inflight_calendrier.clear()
    state.inflight_lives.clear()
    state.inflight_saisons.clear()
    state.inflight_poule.clear()
    state.inflight_detail.clear()
    state.inflight_search.clear()
    if state.cache_lives is not None:
        state.cache_lives.clear()
    if state.cache_search is not None:
        state.cache_search.clear()
    if state.cache_detail is not None:
        state.cache_detail.clear()
    if state.cache_calendrier is not None:
        state.cache_calendrier.clear()
    if state.cache_bilan is not None:
        state.cache_bilan.clear()
    if state.cache_classement is not None:
        state.cache_classement.clear()
    if state.cache_poule is not None:
        state.cache_poule.clear()
