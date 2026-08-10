"""Tests unitaires des helpers communs (common.py) : timeout applicatif, retry
et raisons de miss de cache (cold / expired / api_404)."""

import asyncio
import time

import pytest
from cachetools import TTLCache
from httpx import HTTPStatusError, Request, Response
from mcp.shared.exceptions import McpError

import ffbb_mcp.client  # requis par la fixture autouse de conftest.py
import ffbb_mcp.persistent_cache as persistent_cache
import ffbb_mcp.services
import ffbb_mcp.services.common as common
from ffbb_mcp.persistent_cache import PersistentCache


async def _hanging_coro(sleep_seconds: float) -> str:
    await asyncio.sleep(sleep_seconds)
    return "late"


async def test_safe_call_timeout_raises_and_retries(monkeypatch):
    """Un appel qui pend dépasse le timeout applicatif : TimeoutError → retry,
    puis McpError après épuisement des tentatives."""
    monkeypatch.setattr(common, "_API_TIMEOUT_SECONDS", 0.2)
    calls: list[float] = []

    async def factory():
        calls.append(asyncio.get_running_loop().time())
        return await _hanging_coro(60)

    with pytest.raises(McpError) as exc_info:
        await common._safe_call(
            "op_test", factory, retries=2, base_delay=0.05, max_delay=0.1
        )

    assert len(calls) == 2, "le timeout doit déclencher une nouvelle tentative"
    assert "Timeout" in str(exc_info.value)
    assert "timeout" in str(exc_info.value).lower()


async def test_safe_call_recovers_after_timeout(monkeypatch):
    """Timeout sur la 1re tentative (retriable), succès à la 2e."""
    monkeypatch.setattr(common, "_API_TIMEOUT_SECONDS", 0.2)
    attempts = 0

    async def factory():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return await _hanging_coro(60)
        return "ok"

    result = await common._safe_call(
        "op_test", factory, retries=2, base_delay=0.05, max_delay=0.1
    )
    assert result == "ok"
    assert attempts == 2


async def test_safe_call_no_timeout_normal_path():
    """Sans timeout déclenché, le comportement nominal est inchangé."""
    result = await common._safe_call("op_test", lambda: _hanging_coro(0))
    assert result == "late"


def test_is_retriable_timeout():
    assert common._is_retriable_error(TimeoutError("expired")) is True
    assert common._is_retriable_error(TimeoutError()) is True


def test_is_retriable_http_status():
    request = Request("GET", "https://example.invalid")
    retriable = Response(429, request=request)
    non_retriable = Response(500, request=request)
    assert (
        common._is_retriable_error(
            HTTPStatusError("rate limited", request=request, response=retriable)
        )
        is True
    )
    assert (
        common._is_retriable_error(
            HTTPStatusError("server error", request=request, response=non_retriable)
        )
        is False
    )


def test_is_retriable_misc():
    assert common._is_retriable_error(ValueError("bad input")) is False
    assert common._is_retriable_error(ConnectionError("refused")) is True


# ---------------------------------------------------------------------------
# Raions de miss de cache : cold / expired / api_404
# ---------------------------------------------------------------------------


def _capture_misses(monkeypatch) -> list:
    reasons: list = []

    def hook(cache_name, reason="not_found"):
        reasons.append((cache_name, reason))

    monkeypatch.setattr(ffbb_mcp.services, "_cache_miss_hook", hook)
    return reasons


def test_persistent_cache_get_miss_reasons(monkeypatch, tmp_path):
    """PersistentCache distingue "expired" (TTL dépassé) de "cold" (clé jamais vue)."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(persistent_cache, "_DB_CONN", None)
    cache = PersistentCache(TTLCache(maxsize=10, ttl=60), "test_reasons")

    assert cache.get("missing") is None
    assert cache._last_miss_reason == "cold"

    cache["key"] = "value"
    assert cache.get("key") == "value"
    assert cache._last_miss_reason is None

    cache._expires["key"] = time.time() - 1
    assert cache.get("key") is None
    assert cache._last_miss_reason == "expired"

    conn = persistent_cache._DB_CONN
    if conn is not None:
        conn.close()


async def test_cache_get_cold_miss_reason(monkeypatch):
    """Miss sur cache non persistant (pas d'attribut de raison) → "cold"."""
    reasons = _capture_misses(monkeypatch)
    cache = TTLCache(maxsize=10, ttl=60)

    assert common._cache_get(cache, "k", "test_cache") is None
    assert reasons == [("test_cache", "cold")]


async def test_cache_get_propagates_expired_reason(monkeypatch):
    """Miss sur cache persistant expiré → la raison du PersistentCache est propagée."""
    reasons = _capture_misses(monkeypatch)

    class ExpiredStub:
        _last_miss_reason = "expired"

        def get(self, key, default=None):
            return default

    assert common._cache_get(ExpiredStub(), "k", "test_cache") is None
    assert reasons == [("test_cache", "expired")]


async def test_cache_get_hit_no_miss_recorded(monkeypatch):
    """Hit : aucun miss enregistré."""
    reasons = _capture_misses(monkeypatch)
    cache = TTLCache(maxsize=10, ttl=60)
    cache["k"] = "v"

    assert common._cache_get(cache, "k", "test_cache") == "v"
    assert reasons == []


async def test_dedupe_inflight_records_api_404_reason(monkeypatch):
    """404 HTTP pendant le fetch → miss supplémentaire "api_404" avant re-raise,
    et l'entrée inflight est nettoyée."""
    reasons = _capture_misses(monkeypatch)
    cache = TTLCache(maxsize=10, ttl=60)
    inflight: dict = {}

    async def boom():
        raise HTTPStatusError(
            "404",
            request=Request("GET", "https://ffbb.test/x"),
            response=Response(404),
        )

    with pytest.raises(HTTPStatusError):
        await common._dedupe_inflight(
            cache=cache,
            cache_key="k",
            inflight_map=inflight,
            make_coro=boom,
            cache_name="test_cache",
        )

    assert reasons == [("test_cache", "cold"), ("test_cache", "api_404")]
    assert inflight == {}
