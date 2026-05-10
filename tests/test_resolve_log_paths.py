"""Tests des branches de log dans _resolve_club_and_org."""

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp._state import reset_service_state
from ffbb_mcp.services import _resolve_club_and_org


@pytest.fixture(autouse=True)
def clear_caches():
    reset_service_state()
    yield


@pytest.mark.asyncio
async def test_resolve_logs_debug_when_organisme_id_fetch_fails(caplog):
    """Branch: organisme_id fourni, get_organisme_service lève une exception → debug log."""
    with patch(
        "ffbb_mcp.services.get_organisme_service",
        new_callable=AsyncMock,
        side_effect=RuntimeError("timeout"),
    ):
        caplog.set_level("DEBUG", logger="ffbb-mcp")
        resolved, org_data = await _resolve_club_and_org(
            club_name=None,
            organisme_id=9999,
        )

    assert resolved == []
    assert org_data is None
    assert "9999" in caplog.text
    assert "timeout" in caplog.text


@pytest.mark.asyncio
async def test_resolve_logs_debug_when_first_org_detail_fails(caplog):
    """Branch: club_name fourni, premier org detail fetch échoue → debug log."""
    search_result = [{"id": 42, "nom": "Club Test", "code": "CT"}]

    with (
        patch(
            "ffbb_mcp.services.search_organismes_service",
            new_callable=AsyncMock,
            return_value=search_result,
        ),
        patch(
            "ffbb_mcp.services.get_organisme_service",
            new_callable=AsyncMock,
            side_effect=RuntimeError("503"),
        ),
    ):
        caplog.set_level("DEBUG", logger="ffbb-mcp")
        resolved, org_data = await _resolve_club_and_org(
            club_name="Club Test",
            organisme_id=None,
        )

    assert len(resolved) == 1
    assert resolved[0]["organisme_id"] == 42
    assert org_data is None
    assert "Club Test" in caplog.text
    assert "503" in caplog.text


@pytest.mark.asyncio
async def test_resolve_returns_empty_when_no_club_and_no_id():
    """Cas dégénéré : rien fourni → liste vide."""
    resolved, org_data = await _resolve_club_and_org(
        club_name=None,
        organisme_id=None,
    )

    assert resolved == []
    assert org_data is None
