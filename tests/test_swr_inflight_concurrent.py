"""Tests de concurrence SWR / inflight — R4 audit."""

import asyncio

import pytest
from cachetools import TTLCache

import ffbb_mcp.services.common as common
from ffbb_mcp._state import state
from ffbb_mcp.metrics import get_snapshot, reset_metrics


@pytest.fixture(autouse=True)
def _reset_state():
    reset_metrics()
    state.swr_tasks.clear()
    state.swr_last_fetch.clear()
    yield
    state.swr_tasks.clear()
    state.swr_last_fetch.clear()


async def test_swr_dedup_same_key():
    """Deux appels SWR sur la même clé ne programment qu'une seule tâche."""
    calls = 0

    async def coro():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"ok": 1}

    common._swr_schedule("test", "k1", coro, cache=None)
    common._swr_schedule("test", "k1", coro, cache=None)
    assert len(state.swr_tasks) == 1
    # laisse le temps à la tâche de finir
    await asyncio.sleep(0.1)
    assert len(state.swr_tasks) == 0
    snap = get_snapshot()
    assert snap["swr_total"] == 1
    assert snap["swr_active"] == 0


async def test_swr_max_tasks_dropped(monkeypatch):
    """Au-delà de _SWR_MAX_TASKS, le refresh est abandonné et compté."""
    monkeypatch.setattr(common, "_SWR_MAX_TASKS", 2)

    async def dummy():
        await asyncio.sleep(0.5)
        return {"ok": 1}

    common._swr_schedule("test", "k1", dummy, cache=None)
    common._swr_schedule("test", "k2", dummy, cache=None)
    # troisième doit être droppé
    common._swr_schedule("test", "k3", dummy, cache=None)

    snap = get_snapshot()
    assert len(state.swr_tasks) == 2
    assert snap["swr_total"] == 2
    assert snap["swr_dropped"] == 1
    assert snap["swr_active"] == 2

    await asyncio.sleep(0.6)
    assert len(state.swr_tasks) == 0
    snap2 = get_snapshot()
    assert snap2["swr_active"] == 0


async def test_inflight_dedup_concurrent_calls():
    """N appels concurrents sur la même clé n'exécutent make_coro qu'une fois."""
    cache = TTLCache(maxsize=10, ttl=60)
    inflight: dict = {}
    calls = 0

    async def make_coro():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.1)
        return {"v": 42}

    results = await asyncio.gather(
        *[
            common._dedupe_inflight(
                cache=cache,
                cache_key="k",
                inflight_map=inflight,
                make_coro=make_coro,
                cache_name="test",
            )
            for _ in range(5)
        ]
    )
    assert calls == 1
    assert all(r == {"v": 42} for r in results)
    assert inflight == {}
    # second batch doit servir le cache sans nouvel appel
    results2 = await asyncio.gather(
        *[
            common._dedupe_inflight(
                cache=cache,
                cache_key="k",
                inflight_map=inflight,
                make_coro=make_coro,
                cache_name="test",
            )
            for _ in range(3)
        ]
    )
    assert calls == 1
    assert all(r == {"v": 42} for r in results2)


async def test_inflight_cleanup_after_error():
    """Une erreur dans make_coro nettoie inflight et reste ré-exécutable."""
    cache = TTLCache(maxsize=10, ttl=60)
    inflight: dict = {}
    attempts = 0

    async def boom():
        nonlocal attempts
        attempts += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await common._dedupe_inflight(
            cache=cache,
            cache_key="k",
            inflight_map=inflight,
            make_coro=boom,
            cache_name="test",
        )
    assert inflight == {}
    # retry doit ré-exécuter
    with pytest.raises(RuntimeError):
        await common._dedupe_inflight(
            cache=cache,
            cache_key="k",
            inflight_map=inflight,
            make_coro=boom,
            cache_name="test",
        )
    assert attempts == 2
    assert inflight == {}


async def test_swr_metrics_active_gauge():
    """inc_swr / dec_swr via _swr_schedule sont observables dans les metrics Prometheus."""

    async def coro():
        await asyncio.sleep(0.05)
        return {"ok": 1}

    snap0 = get_snapshot()
    assert snap0["swr_active"] == 0

    common._swr_schedule("test", "gauge-k", coro, cache=None)
    snap1 = get_snapshot()
    assert snap1["swr_active"] == 1
    assert snap1["swr_total"] == snap0["swr_total"] + 1

    await asyncio.sleep(0.1)
    snap2 = get_snapshot()
    assert snap2["swr_active"] == 0
