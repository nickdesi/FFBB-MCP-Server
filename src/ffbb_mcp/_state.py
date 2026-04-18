import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from cachetools import TLRUCache, TTLCache

from ffbb_mcp.cache_strategy import get_static_ttl


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



def _ttu_bilan(_key: Any, value: Any, now: float) -> float:
    return now + get_static_ttl("bilan")

def _ttu_poule(_key: Any, value: Any, now: float) -> float:
    if isinstance(value, dict) and "ttl" in value:
        return now + float(value["ttl"])
    return now + get_static_ttl("rencontre")

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
    cache_lives: TTLCache[Any, Any] = field(
        default_factory=lambda: TTLCache(maxsize=128, ttl=_read_positive_int_env("FFBB_CACHE_TTL_LIVES", get_static_ttl("lives")))
    )
    cache_search: TTLCache[Any, Any] = field(
        default_factory=lambda: TTLCache(maxsize=256, ttl=_read_positive_int_env("FFBB_CACHE_TTL_SEARCH", get_static_ttl("search")))
    )
    cache_detail: TTLCache[Any, Any] = field(
        default_factory=lambda: TTLCache(maxsize=128, ttl=_read_positive_int_env("FFBB_CACHE_TTL_DETAIL", get_static_ttl("organisme")))
    )
    cache_calendrier: TTLCache[Any, Any] = field(
        default_factory=lambda: TTLCache(maxsize=64, ttl=_read_positive_int_env("FFBB_CACHE_TTL_CALENDRIER", get_static_ttl("rencontre")))
    )
    cache_bilan: TLRUCache[Any, Any] = field(
        default_factory=lambda: TLRUCache(maxsize=64, ttu=_ttu_bilan)
    )
    cache_poule: TLRUCache[Any, Any] = field(
        default_factory=lambda: TLRUCache(maxsize=128, ttu=_ttu_poule)
    )

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
    state.cache_lives.clear()
    state.cache_search.clear()
    state.cache_detail.clear()
    state.cache_calendrier.clear()
    state.cache_bilan.clear()
    state.cache_poule.clear()
