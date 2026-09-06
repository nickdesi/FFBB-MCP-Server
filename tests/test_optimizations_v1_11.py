from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ffbb_mcp.server import ffbb_club, ffbb_team_summary, mcp
from ffbb_mcp.services import ffbb_get_classement_service
from ffbb_mcp.sse_patch import apply_fastmcp_json_formatting_patch


@pytest.mark.asyncio
async def test_classement_numeric_sorting(monkeypatch):
    """Vérifie que ffbb_get_classement_service trie numériquement les positions.

    Évite l'ordre lexicographique [1, 10, 11, 2, 3...] et normalise 'position' en int.
    """
    mock_poule = MagicMock()
    mock_poule.model_dump.return_value = {
        "classements": [
            {
                "position": "10",
                "organisme_id": "org10",
                "id_engagement": {"nom": "EQ 10", "numero_equipe": "1"},
            },
            {
                "position": "1",
                "organisme_id": "org1",
                "id_engagement": {"nom": "EQ 1", "numero_equipe": "1"},
            },
            {
                "position": "2",
                "organisme_id": "org2",
                "id_engagement": {"nom": "EQ 2", "numero_equipe": "1"},
            },
            {
                "position": "11",
                "organisme_id": "org11",
                "id_engagement": {"nom": "EQ 11", "numero_equipe": "1"},
            },
        ]
    }

    mock_client = MagicMock()
    mock_client.get_poule_async = AsyncMock(return_value=mock_poule)

    async def mock_get_client():
        return mock_client

    monkeypatch.setattr("ffbb_mcp.services.poule.get_client_async", mock_get_client)

    res = await ffbb_get_classement_service(poule_id=99999, force_refresh=True)

    positions = [item["position"] for item in res]
    assert positions == [1, 2, 10, 11]
    assert res[0]["equipe"] == "EQ 1"
    assert res[1]["equipe"] == "EQ 2"
    assert res[2]["equipe"] == "EQ 10"
    assert res[3]["equipe"] == "EQ 11"


@pytest.mark.asyncio
async def test_fastmcp_json_array_serialization():
    """Vérifie que la sérialisation MCP produit un tableau JSON standard [...] et non du NDJSON {...}\n{...}."""
    apply_fastmcp_json_formatting_patch()

    tool = mcp._tool_manager._tools["ffbb_saisons"]

    # Simuler l'appel low-level FastMCP avec convert_result=True
    with patch("ffbb_mcp.server.get_saisons_service") as mock_saisons:
        mock_saisons.return_value = [
            {"id": "2025-2026", "nom": "2025/2026"},
            {"id": "2024-2025", "nom": "2024/2025"},
        ]

        converted = await tool.run(arguments={}, convert_result=True)

        if isinstance(converted, tuple):
            unstructured, _structured = converted
        else:
            unstructured = converted
            _structured = None

        # Vérification 1 : un seul bloc de texte pour la liste complète
        assert len(unstructured) == 1
        text = unstructured[0].text.strip()

        # Vérification 2 : format strict JSON Array
        assert text.startswith("[") and text.endswith("]")
        import json

        parsed = json.loads(text)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["id"] == "2025-2026"


@pytest.mark.asyncio
async def test_ffbb_club_classement_with_categorie_auto_resolution():
    """Vérifie que ffbb_club(action='classement') résout la poule via categorie='NM3'."""
    mock_resolve_club = AsyncMock(
        return_value=([{"organisme_id": 2001, "nom": "Chamalières"}], None)
    )
    mock_resolve_poule = AsyncMock(return_value=3001)
    mock_classement = AsyncMock(
        return_value=[
            {"position": 1, "equipe": "Chamalières"},
            {"position": 2, "equipe": "Adversaire"},
        ]
    )

    with (
        patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve_club),
        patch("ffbb_mcp.server.resolve_poule_id_service", mock_resolve_poule),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
    ):
        res = await ffbb_club(
            action="classement",
            club_name="Chamalières",
            categorie="NM3",
        )

        mock_resolve_club.assert_called_once_with(
            club_name="Chamalières",
            organisme_id=None,
            categorie="NM3",
            limit=3,
        )
        mock_resolve_poule.assert_called_once_with(2001, "NM3", phase_query=None)
        mock_classement.assert_called_once_with(
            poule_id=3001,
            force_refresh=False,
            target_organisme_id=2001,
            target_num=None,
        )
        assert len(res) == 2
        assert res[0]["position"] == 1


@pytest.mark.asyncio
async def test_ffbb_team_summary_payload_hygiene():
    """Vérifie l'absence de répétition de club_resolu, team et _meta dans last_match et next_match."""
    mock_resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "team": {
                "team_id": "T1",
                "nom_equipe": "Chamalières",
                "numero_equipe": "1",
                "poule_id": "P1",
            },
            "club_resolu": {"organisme_id": "ORG1", "nom": "Chamalières"},
        }
    )
    mock_bilan = AsyncMock(
        return_value={
            "bilan_total": {"match_joues": 1, "gagnes": 1, "perdus": 0},
            "phase_courante": {"poule_id": "P1", "position": 1},
        }
    )
    mock_last = AsyncMock(
        return_value={
            "status": "ok",
            "club_resolu": {"organisme_id": "ORG1", "nom": "Chamalières"},
            "team": {"team_id": "T1"},
            "_meta": {"source": "ffbb_api_live"},
            "date": "2026-09-05 20:00:00",
            "domicile": "Adversaire",
            "score_domicile": "60",
            "exterieur": "Chamalières",
            "score_exterieur": "70",
            "victoire": True,
        }
    )
    mock_next = AsyncMock(
        return_value={
            "status": "ok",
            "club_resolu": {"organisme_id": "ORG1", "nom": "Chamalières"},
            "team": {"team_id": "T1"},
            "_meta": {"source": "ffbb_api_live"},
            "match": {
                "date": "2026-09-12 20:00:00",
                "domicile": "Chamalières",
                "exterieur": "Adversaire 2",
            },
        }
    )

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
    ):
        res = await ffbb_team_summary(
            club_name="Chamalières",
            categorie="NM3",
        )

        assert "team" in res
        assert res["team"]["nom_equipe"] == "Chamalières"

        # last_match ne doit pas dupliquer club_resolu, team, status, _meta
        last_m = res["last_match"]
        assert last_m is not None
        assert "club_resolu" not in last_m
        assert "team" not in last_m
        assert "_meta" not in last_m
        assert "status" not in last_m
        assert last_m["date"] == "2026-09-05 20:00:00"
        assert last_m["victoire"] is True

        # next_match ne doit pas dupliquer club_resolu, team, status, _meta et doit être aplati
        next_m = res["next_match"]
        assert next_m is not None
        assert "club_resolu" not in next_m
        assert "team" not in next_m
        assert "_meta" not in next_m
        assert "status" not in next_m
        assert next_m["date"] == "2026-09-12 20:00:00"
        assert next_m["domicile"] == "Chamalières"
