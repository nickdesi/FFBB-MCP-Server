"""Tests des resources MCP FFBB."""

import json
from datetime import date
from unittest.mock import AsyncMock, Mock

import pytest

from ffbb_mcp.resources import register_resources


class DummyMCP:
    def __init__(self):
        self.resources = {}

    def resource(self, uri: str):
        def decorator(func):
            self.resources[uri] = func
            return func

        return decorator


@pytest.fixture
def registered_resources():
    mcp = DummyMCP()
    register_resources(mcp)
    return mcp.resources


@pytest.mark.asyncio
async def test_resources_return_pruned_json(registered_resources, monkeypatch):
    get_saisons = AsyncMock(return_value={"date": date(2026, 5, 10)})
    get_competition = AsyncMock(return_value={"id": 11, "empty": None})
    get_poule = AsyncMock(return_value={"id": 22, "items": [None, {"ok": True}]})
    get_organisme = AsyncMock(return_value={"id": 33, "name": "Club"})
    get_rencontre = AsyncMock(return_value={"id": 44, "score_a": 80})
    get_salle = AsyncMock(return_value={"id": 55, "libelle": "Gymnase"})
    get_officiel = AsyncMock(return_value={"id": 66, "nom": "Dupont"})
    get_entraineur = AsyncMock(return_value={"id": 77, "nom": "Durand"})

    monkeypatch.setattr("ffbb_mcp.services.get_saisons_service", get_saisons)
    monkeypatch.setattr("ffbb_mcp.services.get_competition_service", get_competition)
    monkeypatch.setattr("ffbb_mcp.services.get_poule_service", get_poule)
    monkeypatch.setattr("ffbb_mcp.services.get_organisme_service", get_organisme)
    monkeypatch.setattr("ffbb_mcp.services.get_rencontre_service", get_rencontre)
    monkeypatch.setattr("ffbb_mcp.services.get_salle_service", get_salle)
    monkeypatch.setattr("ffbb_mcp.services.get_officiel_service", get_officiel)
    monkeypatch.setattr("ffbb_mcp.services.get_entraineur_service", get_entraineur)

    saisons = json.loads(await registered_resources["ffbb://saisons"]())
    competition = json.loads(
        await registered_resources["ffbb://competition/{competition_id}"](11)
    )
    poule = json.loads(await registered_resources["ffbb://poule/{poule_id}"](22))
    organisme = json.loads(
        await registered_resources["ffbb://organisme/{organisme_id}"](33)
    )
    rencontre = json.loads(
        await registered_resources["ffbb://rencontre/{rencontre_id}"](44)
    )
    salle = json.loads(await registered_resources["ffbb://salle/{salle_id}"](55))
    officiel = json.loads(
        await registered_resources["ffbb://officiel/{officiel_id}"](66)
    )
    entraineur = json.loads(
        await registered_resources["ffbb://entraineur/{entraineur_id}"](77)
    )

    assert saisons == {"date": "2026-05-10"}
    assert competition == {"id": 11}
    assert poule == {"id": 22, "items": [{"ok": True}]}
    assert organisme == {"id": 33, "name": "Club"}
    assert rencontre == {"id": 44, "score_a": 80}
    assert salle == {"id": 55, "libelle": "Gymnase"}
    assert officiel == {"id": 66, "nom": "Dupont"}
    assert entraineur == {"id": 77, "nom": "Durand"}
    get_competition.assert_awaited_once_with(11)
    get_poule.assert_awaited_once_with(22)
    get_organisme.assert_awaited_once_with(33)
    get_rencontre.assert_awaited_once_with(44)
    get_salle.assert_awaited_once_with(55)
    get_officiel.assert_awaited_once_with(66)
    get_entraineur.assert_awaited_once_with(77)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("uri", "service_name", "args"),
    [
        ("ffbb://saisons", "get_saisons_service", ()),
        ("ffbb://competition/{competition_id}", "get_competition_service", (11,)),
        ("ffbb://poule/{poule_id}", "get_poule_service", (22,)),
        ("ffbb://organisme/{organisme_id}", "get_organisme_service", (33,)),
        ("ffbb://rencontre/{rencontre_id}", "get_rencontre_service", (44,)),
        ("ffbb://salle/{salle_id}", "get_salle_service", (55,)),
        ("ffbb://officiel/{officiel_id}", "get_officiel_service", (66,)),
        ("ffbb://entraineur/{entraineur_id}", "get_entraineur_service", (77,)),
    ],
)
async def test_resources_convert_service_errors(
    registered_resources, monkeypatch, uri, service_name, args
):
    source_error = ValueError("boom")
    converted_error = RuntimeError("converted")
    service = AsyncMock(side_effect=source_error)
    handle_api_error = Mock(return_value=converted_error)

    monkeypatch.setattr(f"ffbb_mcp.services.{service_name}", service)
    monkeypatch.setattr("ffbb_mcp.services.handle_api_error", handle_api_error)

    with pytest.raises(RuntimeError, match="converted"):
        await registered_resources[uri](*args)

    handle_api_error.assert_called_once_with(source_error)
