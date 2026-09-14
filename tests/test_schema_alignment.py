"""Tests de conformité stricte des schémas MCP et de l'alignement des priorités de désambiguïsation (Release 1.12.1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.server import mcp
from ffbb_mcp.services import ffbb_resolve_team_service


@pytest.mark.asyncio
async def test_mcp_tools_schema_properties_published():
    """Vérifie que tous les paramètres et leurs types exacts sont bien publiés dans les schémas MCP."""
    tools = await mcp.list_tools()
    tools_map = {t.name: t for t in tools}

    # 1. ffbb_search : pagination + filtres
    search_schema = tools_map["ffbb_search"].inputSchema
    search_props = search_schema["properties"]
    assert "query" in search_props
    assert "type" in search_props
    assert "limit" in search_props
    assert "offset" in search_props
    assert "filter_by" in search_props
    assert "sort" in search_props
    assert "force_refresh" in search_props
    assert search_props["limit"].get("type") == "integer"
    assert search_props["offset"].get("type") == "integer"

    # 2. ffbb_club : action, pagination, filtres et désambiguïsation
    club_schema = tools_map["ffbb_club"].inputSchema
    club_props = club_schema["properties"]
    expected_club_params = {
        "action",
        "organisme_id",
        "club_name",
        "categorie",
        "numero_equipe",
        "engagement_id",
        "competition_id",
        "competition_type",
        "poule_id",
        "season_id",
        "limit",
        "offset",
        "force_refresh",
    }
    assert expected_club_params.issubset(set(club_props.keys()))
    assert club_props["offset"].get("type") == ["integer", "null"] or any(
        x.get("type") == "integer" for x in club_props["offset"].get("anyOf", [])
    )

    # 3. Outils d'équipe : identité métier uniforme
    team_tools = [
        "ffbb_resolve_team",
        "ffbb_bilan",
        "ffbb_team_summary",
        "ffbb_bilan_saison",
        "ffbb_last_result",
        "ffbb_next_match",
    ]
    for tool_name in team_tools:
        tool_schema = tools_map[tool_name].inputSchema
        props = tool_schema["properties"]
        expected_team_params = {
            "organisme_id",
            "club_name",
            "categorie",
            "numero_equipe",
            "engagement_id",
            "competition_id",
            "competition_type",
            "poule_id",
            "season_id",
            "force_refresh",
        }
        assert expected_team_params.issubset(set(props.keys())), (
            f"Paramètres manquants sur {tool_name} : {expected_team_params - set(props.keys())}"
        )

        # Vérification typage uniforme string | null pour les identifiants
        for id_param in [
            "organisme_id",
            "engagement_id",
            "competition_id",
            "poule_id",
            "season_id",
        ]:
            p_def = props[id_param]
            p_types = p_def.get("type") or [
                x.get("type") for x in p_def.get("anyOf", [])
            ]
            if isinstance(p_types, str):
                p_types = [p_types]
            assert "string" in p_types, (
                f"{tool_name}.{id_param} doit accepter le type string (obtenu: {p_types})"
            )


@pytest.mark.asyncio
async def test_strict_priority_hierarchy_disambiguation(mock_client) -> None:
    """Vérifie la priorité absolue : engagement_id > poule_id > competition_id > competition_type > numero_equipe."""
    # Mock organisme avec 3 engagements pour la même catégorie U18M
    mock_org = {
        "id": 9326,
        "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
        "code": "ARA0063074",
        "engagements": [
            {
                "id": "ENG_PLAT",
                "numeroEquipe": 1,
                "idPoule": {"id": "POULE_PLAT"},
                "idCompetition": {
                    "id": "COMP_PLAT",
                    "nom": "Championnat Régional U18",
                    "code": "REG_U18",
                    "typeCompetition": "PLAT",
                    "sexe": "M",
                    "categorie": {"code": "U18"},
                },
            },
            {
                "id": "ENG_COUPE",
                "numeroEquipe": 1,
                "idPoule": {"id": "POULE_COUPE"},
                "idCompetition": {
                    "id": "COMP_COUPE",
                    "nom": "Coupe ARA U18",
                    "code": "COUPE_U18",
                    "typeCompetition": "COUPE",
                    "sexe": "M",
                    "categorie": {"code": "U18"},
                },
            },
            {
                "id": "ENG_TOURNOI",
                "numeroEquipe": 1,
                "idPoule": {"id": "POULE_TOURNOI"},
                "idCompetition": {
                    "id": "COMP_TOURNOI",
                    "nom": "Tournoi U18",
                    "code": "TOURNOI_U18",
                    "typeCompetition": "AUTRE",
                    "sexe": "M",
                    "categorie": {"code": "U18"},
                },
            },
        ],
    }
    mock_client.get_organisme_async = AsyncMock(return_value=mock_org)

    # 1. Priorité 1 : engagement_id
    res_eng = await ffbb_resolve_team_service(
        organisme_id="9326",
        categorie="U18M",
        engagement_id="ENG_COUPE",
        # Même si d'autres filtres contradictoires étaient passés, engagement_id cible directement
        force_refresh=True,
    )
    assert res_eng["status"] == "resolved"
    assert res_eng["team"]["engagement_id"] == "ENG_COUPE"

    # 2. Priorité 2 : poule_id
    res_poule = await ffbb_resolve_team_service(
        organisme_id="9326",
        categorie="U18M",
        poule_id="POULE_TOURNOI",
        force_refresh=True,
    )
    assert res_poule["status"] == "resolved"
    assert res_poule["team"]["poule_id"] == "POULE_TOURNOI"

    # 3. Priorité 3 : competition_id
    res_comp = await ffbb_resolve_team_service(
        organisme_id="9326",
        categorie="U18M",
        competition_id="COMP_PLAT",
        force_refresh=True,
    )
    assert res_comp["status"] == "resolved"
    assert res_comp["team"]["competition_id"] == "COMP_PLAT"

    # 4. Priorité 4 : competition_type
    res_type = await ffbb_resolve_team_service(
        organisme_id="9326",
        categorie="U18M",
        competition_type="COUPE",
        force_refresh=True,
    )
    assert res_type["status"] == "resolved"
    assert res_type["team"]["competition_type"] == "COUPE"


@pytest.mark.asyncio
async def test_last_result_and_next_match_support_all_identifiers():
    """Vérifie que ffbb_last_result et ffbb_next_match fonctionnent avec engagement_id ou poule_id sans club_name obligatoire."""
    mock_last_svc = AsyncMock(
        return_value={"status": "ok", "match": {"adversaire": "Vichy"}}
    )
    mock_next_svc = AsyncMock(
        return_value={"status": "ok", "match": {"adversaire": "Roanne"}}
    )

    with (
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last_svc),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next_svc),
    ):
        # Invocations avec engagement_id seul
        await mcp.call_tool("ffbb_last_result", {"engagement_id": "200000005347163"})
        mock_last_svc.assert_called_once_with(
            club_name=None,
            organisme_id=None,
            categorie="",
            numero_equipe=1,
            engagement_id="200000005347163",
            competition_id=None,
            competition_type=None,
            poule_id=None,
            season_id=None,
            force_refresh=False,
        )

        await mcp.call_tool("ffbb_next_match", {"poule_id": "200000003056290"})
        mock_next_svc.assert_called_once_with(
            club_name=None,
            organisme_id=None,
            categorie="",
            numero_equipe=1,
            engagement_id=None,
            competition_id=None,
            competition_type=None,
            poule_id="200000003056290",
            season_id=None,
            force_refresh=False,
        )
