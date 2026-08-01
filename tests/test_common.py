"""Tests unitaires des helpers communs (common.py) : timeout applicatif et retry."""

import asyncio

import pytest
from httpx import HTTPStatusError, Request, Response
from mcp.shared.exceptions import McpError

import ffbb_mcp.client  # noqa: F401  # requis par la fixture autouse de conftest.py
import ffbb_mcp.services.common as common


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
    assert common._is_retriable_error(
        HTTPStatusError("rate limited", request=request, response=retriable)
    ) is True
    assert common._is_retriable_error(
        HTTPStatusError("server error", request=request, response=non_retriable)
    ) is False


def test_is_retriable_misc():
    assert common._is_retriable_error(ValueError("bad input")) is False
    assert common._is_retriable_error(ConnectionError("refused")) is True
