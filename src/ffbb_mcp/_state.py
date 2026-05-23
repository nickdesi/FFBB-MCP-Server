from __future__ import annotations

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
    inflight_detail: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    inflight_search: dict[str, asyncio.Task[Any]] = field(default_factory=dict)

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


state = _ServiceState()


def reset_service_state() -> None:
    global state
    state.inflight_bilan.clear()
    state.inflight_calendrier.clear()
    state.inflight_poule.clear()
    state.inflight_detail.clear()
    state.inflight_search.clear()
    if state.cache_lives is not None:
        state.cache_lives.clear()
    if state.cache_search is not None:
        state.cache_search.clear()
    if state.cache_competition is not None:
        state.cache_competition.clear()
    if state.cache_organisme is not None:
        state.cache_organisme.clear()
    if state.cache_saisons is not None:
        state.cache_saisons.clear()
    if state.cache_calendrier is not None:
        state.cache_calendrier.clear()
    if state.cache_bilan is not None:
        state.cache_bilan.clear()
    if state.cache_classement is not None:
        state.cache_classement.clear()
    if state.cache_poule is not None:
        state.cache_poule.clear()
    if state.cache_salle is not None:
        state.cache_salle.clear()
