"""Non-régression PLAT/brassage vs DIV : calendrier, lives, bilan, contrats.

Cas réel modélisé (SAINT DENIS US 11781, U13M TOURNOIS BRASSAGE PLAT,
engagement 200000005387270, poule 200000003061669, match 200000014810947
Bobigny 26/09/2026 15h ; contrôle DIV SEM1 200000005376155) — prouvé en live
avec les vrais IDs. Ici on utilise des IDs synthétiques par test : les caches
service persistants (SQLite partagé) rendraient des IDs réels non hermétiques
(persist async en tâche de fond pouvant traverser les frontières de tests).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ffbb_mcp.services.calendar import get_calendrier_club_service


@pytest.fixture(autouse=True)
def _isolate_persistent_caches():
    """Vide mémoire + SQLite pour des tests hermétiques."""
    from ffbb_mcp._state import state

    caches = (
        state.cache_calendrier,
        state.cache_poule,
        state.cache_equipes,
        state.cache_lives,
        state.cache_saisons,
    )
    for cache in caches:
        try:
            if cache is not None:
                cache.clear_db()
        except Exception:
            pass
    yield
    for cache in caches:
        try:
            if cache is not None:
                cache.clear_db()
        except Exception:
            pass


def _org_mock(nom, engagements):
    org = MagicMock()
    org.model_dump = MagicMock(return_value={"nom": nom, "engagements": engagements})
    return org


def _poule_mock(rencontres):
    poule = MagicMock()
    poule.model_dump = MagicMock(return_value={"rencontres": rencontres})
    return poule


def _salle_mock():
    salle = MagicMock()
    salle.model_dump = MagicMock(return_value={"id": "s1"})
    return salle


def _plat_team(org_ids):
    """Équipe PLAT avec numero_equipe vide (cas brassage U13M)."""
    eng, poule, comp = org_ids["eng"], org_ids["poule"], org_ids["comp"]
    return {
        "id": eng,
        "idCompetition": {
            "id": comp,
            "nom": "TOURNOIS BRASSAGE U13 MASCULINS",
            "categorie": {"code": "U13"},
            "sexe": "M",
            "typeCompetition": "PLAT",
            "saison": {"id": "1037"},
        },
        "idPoule": {"id": poule},
        "numeroEquipe": "",
    }


def _plat_match(org_ids, match_id="m-plat-1"):
    eng = org_ids["eng"]
    return {
        "id": match_id,
        "date_rencontre": "2026-09-26 15:00:00",
        "nomEquipe1": "ATHLETIC CLUB BOBIGNY",
        "nomEquipe2": "SAINT DENIS UNION SPORTS",
        "idEngagementEquipe1": {"id": "990000000000009"},
        "idEngagementEquipe2": {"id": eng},
        "joue": 0,
        "numeroJournee": 18,
        "statut": None,
    }


# Jeux d'IDs synthétiques distincts par test (herméticité, cf. docstring).
IDS_C1 = {
    "org": "99101",
    "eng": "991010000000001",
    "poule": "991010000000002",
    "comp": "991010000000003",
}
IDS_C2 = {
    "org": "99102",
    "eng": "991020000000001",
    "poule": "991020000000002",
    "comp": "991020000000003",
}
IDS_C3 = {
    "org": "99103",
    "eng": "991030000000001",
    "poule": "991030000000002",
    "comp": "991030000000003",
}
IDS_DIV = {
    "org": "99104",
    "eng": "991040000000001",
    "poule": "991040000000002",
    "comp": "991040000000003",
}
IDS_TOOL = {
    "org": "99105",
    "eng": "991050000000001",
    "poule": "991050000000002",
    "comp": "991050000000003",
}
IDS_LIVES = {
    "org": "99106",
    "eng": "991060000000001",
    "poule": "991060000000002",
    "comp": "991060000000003",
}
IDS_BILAN = {
    "org": "99107",
    "eng": "991070000000001",
    "poule": "991070000000002",
    "comp": "991070000000003",
}


def _div_team(ids):
    return {
        "id": ids["eng"],
        "idCompetition": {
            "id": ids["comp"],
            "nom": "Départementale masculine seniors - Division 2",
            "categorie": {"code": "SE"},
            "sexe": "M",
            "typeCompetition": "DIV",
            "saison": {"id": "1037"},
        },
        "idPoule": {"id": ids["poule"]},
        "numeroEquipe": 1,
    }


def _div_match(ids):
    return {
        "id": "m-div-1",
        "date_rencontre": "2026-09-26 20:30:00",
        "nomEquipe1": "SAINT DENIS UNION SPORTS - 1",
        "nomEquipe2": "US BASKET DRANCY - 2",
        "idEngagementEquipe1": {"id": ids["eng"]},
        "idEngagementEquipe2": {"id": "991040000000009"},
        "joue": 0,
        "numeroJournee": 1,
        "statut": None,
    }


@pytest.mark.asyncio
async def test_plat_engagement_bypasses_friendly_name_exclusion(
    patch_get_client, mock_client
):
    """Le filtre engagement exact retrouve le match PLAT malgré 'TOURNOI' dans le nom."""
    mock_client.get_organisme_async = AsyncMock(
        return_value=_org_mock("SAINT DENIS UNION SPORTS", [_plat_team(IDS_C1)])
    )
    mock_client.get_poule_async = AsyncMock(
        return_value=_poule_mock([_plat_match(IDS_C1)])
    )
    mock_client.get_salle_async = AsyncMock(return_value=_salle_mock())

    result = await get_calendrier_club_service(
        organisme_id=IDS_C1["org"],
        categorie="U13M",
        engagement_id=IDS_C1["eng"],
        poule_id=IDS_C1["poule"],
        season_id="1037",
        status_filter=["scheduled"],
        scope="team",
        force_refresh=True,
    )

    assert result.get("status") != "not_found"
    assert "warning" not in result
    assert [m["id"] for m in result["items"]] == ["m-plat-1"]


@pytest.mark.asyncio
async def test_plat_engagement_without_categorie(patch_get_client, mock_client):
    """Même appel sans categorie : l'engagement exact suffit."""
    mock_client.get_organisme_async = AsyncMock(
        return_value=_org_mock("SAINT DENIS UNION SPORTS", [_plat_team(IDS_C2)])
    )
    mock_client.get_poule_async = AsyncMock(
        return_value=_poule_mock([_plat_match(IDS_C2)])
    )
    mock_client.get_salle_async = AsyncMock(return_value=_salle_mock())

    result = await get_calendrier_club_service(
        organisme_id=IDS_C2["org"],
        engagement_id=IDS_C2["eng"],
        poule_id=IDS_C2["poule"],
        season_id="1037",
        status_filter=["scheduled"],
        scope="team",
        force_refresh=True,
    )

    assert [m["id"] for m in result["items"]] == ["m-plat-1"]


@pytest.mark.asyncio
async def test_poule_id_mismatch_stays_not_found(patch_get_client, mock_client):
    """Un poule_id contredisant l'engagement reste strict (pas d'élargissement)."""
    mock_client.get_organisme_async = AsyncMock(
        return_value=_org_mock("SAINT DENIS UNION SPORTS", [_plat_team(IDS_C3)])
    )
    mock_client.get_poule_async = AsyncMock(
        return_value=_poule_mock([_plat_match(IDS_C3)])
    )

    result = await get_calendrier_club_service(
        organisme_id=IDS_C3["org"],
        engagement_id=IDS_C3["eng"],
        poule_id="999999999999",
        season_id="1037",
        scope="team",
        force_refresh=True,
    )

    assert result.get("status") == "not_found"
    assert result["items"] == []


@pytest.mark.asyncio
async def test_div_control_unchanged(patch_get_client, mock_client):
    """Le chemin DIV classique reste intact (total, tri, premier match)."""
    mock_client.get_organisme_async = AsyncMock(
        return_value=_org_mock("SAINT DENIS UNION SPORTS", [_div_team(IDS_DIV)])
    )
    mock_client.get_poule_async = AsyncMock(
        return_value=_poule_mock([_div_match(IDS_DIV)])
    )
    mock_client.get_salle_async = AsyncMock(return_value=_salle_mock())

    result = await get_calendrier_club_service(
        organisme_id=IDS_DIV["org"],
        categorie="SEM1",
        numero_equipe=1,
        season_id="1037",
        status_filter=["scheduled"],
        scope="team",
        force_refresh=True,
    )

    assert result["_meta"]["total"] == 1
    assert result["items"][0]["id"] == "m-div-1"
    assert result["items"][0]["is_next_match"] is True


@pytest.mark.asyncio
async def test_tool_accepts_engagement_without_org(patch_get_client, mock_client):
    """ffbb_club(calendrier) résout l'organisme depuis l'engagement seul."""
    from ffbb_mcp.server import ffbb_club

    mock_client.get_organisme_async = AsyncMock(
        return_value=_org_mock("SAINT DENIS UNION SPORTS", [_plat_team(IDS_TOOL)])
    )
    mock_client.get_poule_async = AsyncMock(
        return_value=_poule_mock([_plat_match(IDS_TOOL)])
    )
    mock_client.get_salle_async = AsyncMock(return_value=_salle_mock())

    eng = MagicMock()
    eng.idOrganisme = IDS_TOOL["org"]
    eng_client = MagicMock()
    eng_client.get_engagement_async = AsyncMock(return_value=eng)

    with patch(
        "ffbb_mcp.client.FFBBClientFactory.get_client_async",
        new_callable=AsyncMock,
        return_value=eng_client,
    ):
        result = await ffbb_club(
            action="calendrier",
            engagement_id=IDS_TOOL["eng"],
            poule_id=IDS_TOOL["poule"],
            season_id="1037",
            status_filter=["scheduled"],
            limit=20,
            force_refresh=True,
            scope="team",
            strict_filters=True,
        )

    assert isinstance(result, dict)
    assert [m["id"] for m in result["items"]] == ["m-plat-1"]


@pytest.mark.asyncio
async def test_tool_error_is_dict_envelope():
    """structured_content homogène : l'erreur calendrier est un objet, pas une liste."""
    from ffbb_mcp.server import ffbb_club

    result = await ffbb_club(action="calendrier")

    assert isinstance(result, dict)
    assert result["items"] == []
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_lives_scheduled_fallback_returns_plat_match(
    patch_get_client, mock_client
):
    """ffbb_lives(include_scheduled) remonte le programmé via le fallback calendrier."""
    from ffbb_mcp.services.poule import get_lives_service

    mock_client.get_lives_async = AsyncMock(return_value=[])
    mock_client.get_organisme_async = AsyncMock(
        return_value=_org_mock("SAINT DENIS UNION SPORTS", [_plat_team(IDS_LIVES)])
    )
    mock_client.get_poule_async = AsyncMock(
        return_value=_poule_mock([_plat_match(IDS_LIVES)])
    )
    mock_client.get_salle_async = AsyncMock(return_value=_salle_mock())

    result = await get_lives_service(
        organisme_id=IDS_LIVES["org"],
        engagement_id=IDS_LIVES["eng"],
        include_scheduled=True,
        include_calendar_fallback=True,
    )

    ids = [str(m.get("id")) for m in result]
    assert "m-plat-1" in ids


@pytest.mark.asyncio
async def test_bilan_categorie_normalized_from_team(patch_get_client, mock_client):
    """ffbb_bilan(engagement seul) expose 'U13M', pas ''."""
    from ffbb_mcp.services.bilan import ffbb_saison_bilan_service

    mock_client.get_organisme_async = AsyncMock(
        return_value=_org_mock("SAINT DENIS UNION SPORTS", [_plat_team(IDS_BILAN)])
    )
    mock_client.get_poule_async = AsyncMock(
        return_value=_poule_mock([_plat_match(IDS_BILAN)])
    )
    eng = MagicMock()
    eng.idOrganisme = IDS_BILAN["org"]
    eng.idCompetition = IDS_BILAN["comp"]
    eng.idPoule = IDS_BILAN["poule"]
    mock_client.get_engagement_async = AsyncMock(return_value=eng)

    with patch(
        "ffbb_mcp.client.FFBBClientFactory.get_client_async",
        new_callable=AsyncMock,
        return_value=mock_client,
    ):
        result = await ffbb_saison_bilan_service(
            engagement_id=IDS_BILAN["eng"],
            poule_id=IDS_BILAN["poule"],
            season_id="1037",
            force_refresh=True,
        )

    assert result.get("categorie") == "U13M"
