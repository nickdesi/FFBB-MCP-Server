from unittest.mock import AsyncMock, patch

import pytest
from mcp.shared.exceptions import McpError

from ffbb_mcp.server import ffbb_bilan, ffbb_team_summary
from ffbb_mcp.services.common import handle_api_error
from ffbb_mcp.services.search import (
    _score_organisme_relevance,
    search_organismes_service,
)


def test_score_organisme_relevance_ranks_exact_commune_first():
    montjoie = {
        "id": 10017,
        "nom": "LA MONTJOIE SAINT DENIS EN VAL",
        "commune": {"libelle": "SAINT-DENIS-EN-VAL"},
        "code": "CVL0045078",
    }
    other_club = {
        "id": 5001,
        "nom": "SAINT DENIS-COPE. BC 2 ETOILES",
        "commune": {"libelle": "LA COPECHAGNIERE"},
        "code": "PDL0085000",
    }
    query = "Saint-Denis-en-Val"
    score_montjoie = _score_organisme_relevance(montjoie, query)
    score_other = _score_organisme_relevance(other_club, query)

    assert score_montjoie > score_other
    assert score_montjoie > 80.0


@pytest.mark.asyncio
async def test_search_organismes_reorders_by_relevance():
    mock_results = [
        {
            "id": 5001,
            "nom": "SAINT DENIS-COPE. BC 2 ETOILES",
            "commune": {"libelle": "LA COPECHAGNIERE"},
            "code": "PDL0085000",
        },
        {
            "id": 10017,
            "nom": "LA MONTJOIE SAINT DENIS EN VAL",
            "commune": {"libelle": "SAINT-DENIS-EN-VAL"},
            "code": "CVL0045078",
        },
    ]
    with (
        patch(
            "ffbb_mcp.services.search._search_generic",
            AsyncMock(return_value=mock_results),
        ),
        patch(
            "ffbb_mcp.services.search.filter_inactive_ententes",
            AsyncMock(side_effect=lambda x, **kw: x),
        ),
    ):
        res = await search_organismes_service("Saint-Denis-en-Val", force_refresh=True)
        assert len(res) == 2
        assert res[0]["id"] == 10017
        assert res[0]["nom"] == "LA MONTJOIE SAINT DENIS EN VAL"


@pytest.mark.asyncio
async def test_require_club_identifier_raises_mcp_error():
    with pytest.raises(McpError) as exc_info:
        await ffbb_bilan()
    assert "Paramètre manquant" in str(exc_info.value)
    assert "organisme_id" in str(exc_info.value)

    with pytest.raises(McpError) as exc_info_summary:
        await ffbb_team_summary()
    assert "Paramètre manquant" in str(exc_info_summary.value)


@pytest.mark.asyncio
async def test_team_summary_short_answer_formats_perdus_and_dynamique_cleanly():
    mock_resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "team": {"team_label": "SEM1", "engagement_id": "200000005343882"},
            "club_resolu": {"organisme_id": 10017, "nom": "LA MONTJOIE"},
        }
    )
    mock_bilan = AsyncMock(
        return_value={
            "status": "ok",
            "phase_courante": {"competition": "Régionale 3 Masculine"},
            "bilan_total": {"gagnes": 0, "perdus": 1, "nuls": 0},
        }
    )
    mock_last = AsyncMock(
        return_value={
            "status": "ok",
            "presentation": {"short_answer": "Défaite 65 à 70."},
        }
    )
    mock_next = AsyncMock(
        return_value={
            "status": "no_upcoming_match",
            "presentation": {"short_answer": "Aucun match prévu."},
        }
    )

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
    ):
        res = await ffbb_team_summary(
            engagement_id="200000005343882",
        )
        assert res["status"] == "ok"
        short_ans = res["presentation"]["short_answer"]
        # Doit afficher 1 défaite (pas 0 défaites)
        assert "1 défaite" in short_ans
        assert "0 victoires" in short_ans
        # Ne doit JAMAIS interpoler de dict Python brut
        assert "{'forme'" not in short_ans
        assert "data" not in res  # Déduplication validée


def test_handle_api_error_403_mentions_invalid_id_and_archived_season():
    from httpx import HTTPStatusError, Request, Response

    req = Request("GET", "https://api.ffbb.app/items/rencontres/999999999")
    resp = Response(
        403,
        request=req,
        headers={"content-type": "application/json"},
        json={"errors": [{"message": "Forbidden"}]},
    )
    err = HTTPStatusError("403 Forbidden", request=req, response=resp)

    mcp_err = handle_api_error(err)
    msg = str(mcp_err)
    assert "invalide ou inexistant" in msg
    assert "saison archivée" in msg


@pytest.mark.asyncio
async def test_find_team_candidates_formats_placeholder_time_as_horaire_a_fixer():
    from ffbb_mcp.services.search import ffbb_find_team_candidates_service

    mock_team = {
        "engagement_id": "200000005343882",
        "team_label": "SEF",
        "competition_id": "1",
        "poule_id": "100",
        "competition_name": "Régionale 1 Féminine",
        "nom_equipe": "MONTJOIE",
    }
    mock_match = (
        {
            "id": "1",
            "nomEquipe1": "MONTJOIE",
            "nomEquipe2": "CMPJM INGRE BASKET - 2",
            "date_rencontre": "2026-10-10",
            "heure": "00:00:00",
            "horaire": "1",
        },
        {},
    )

    with (
        patch(
            "ffbb_mcp.services.search.resolve_club_and_org",
            AsyncMock(
                return_value=(
                    [{"nom": "MONTJOIE", "organisme_id": 10017}],
                    {"id": 10017, "nom": "MONTJOIE"},
                )
            ),
        ),
        patch(
            "ffbb_mcp.services.ffbb_equipes_club_service",
            AsyncMock(return_value=[mock_team]),
        ),
        patch(
            "ffbb_mcp.services._fetch_poule_matches",
            AsyncMock(return_value=[mock_match]),
        ),
    ):
        res = await ffbb_find_team_candidates_service(
            organisme_id=10017,
            include_next_match=True,
        )
        assert res["status"] in ("resolved", "ambiguous")
        cand = res["candidates"][0]
        assert cand["next_match"] is not None
        assert cand["next_match"]["heure"] == "Horaire à fixer"


@pytest.mark.asyncio
async def test_team_summary_match_items_have_no_nested_data_or_presentation():
    """Vérifie que last_match et next_match dans ffbb_team_summary ne ré-imbriquent pas
    data, presentation, provenance ou team."""
    mock_resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "team": {"team_label": "SEM1", "engagement_id": "200000005343882"},
            "club_resolu": {"organisme_id": 10017, "nom": "LA MONTJOIE"},
        }
    )
    mock_bilan = AsyncMock(
        return_value={
            "status": "ok",
            "phase_courante": {"competition": "Régionale 3 Masculine"},
            "bilan_total": {"gagnes": 0, "perdus": 1, "nuls": 0},
        }
    )
    mock_last = AsyncMock(
        return_value={
            "status": "ok",
            "data": {
                "team": {"name": "LA MONTJOIE"},
                "match": {
                    "context_label": "Dernier match",
                    "home_team": "ASJ",
                    "away_team": "LA MONTJOIE",
                },
            },
            "presentation": {"short_answer": "Défaite 65 à 70."},
            "provenance": {"source": "ffbb_api_live"},
            "score_domicile": 70,
            "score_exterieur": 65,
            "date": "2026-09-20",
        }
    )
    mock_next = AsyncMock(
        return_value={
            "status": "ok",
            "data": {
                "team": {"name": "LA MONTJOIE"},
                "match": {
                    "context_label": "Prochain match",
                    "home_team": "LA MONTJOIE",
                    "away_team": "CMPJM",
                },
            },
            "presentation": {"short_answer": "Prochain match contre CMPJM."},
            "provenance": {"source": "ffbb_api_live"},
            "date": "2026-09-27",
            "adversaire": "CMPJM",
        }
    )

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
    ):
        res = await ffbb_team_summary(
            engagement_id="200000005343882",
        )
        assert res["status"] == "ok"
        lm = res["last_match"]
        nm = res["next_match"]
        for item in (lm, nm):
            assert "data" not in item
            assert "presentation" not in item
            assert "provenance" not in item
            assert "team" not in item
            assert "club_resolu" not in item
            assert "status" not in item
        assert lm["date"] == "2026-09-20"
        assert lm["score_domicile"] == 70
        assert nm["adversaire"] == "CMPJM"


@pytest.mark.asyncio
async def test_fastmcp_structured_content_deduplication():
    """Vérifie que convert_result sérialise un texte concis dans content[0]
    quand le dictionnaire contient une présentation, au lieu de dupliquer tout le JSON."""
    from ffbb_mcp.server import mcp

    tool = mcp._tool_manager.get_tool("ffbb_team_summary")
    dummy_res = {
        "status": "ok",
        "team": {"nom_equipe": "SEM1"},
        "summary": {"match_joues": 1, "gagnes": 0, "perdus": 1},
        "presentation": {
            "short_answer": "Bilan pour SEM1 : 0 victoires, 1 défaite.",
            "detail_line": "Dernier match perdu.",
        },
        "provenance": {"source": "ffbb_api_live"},
    }
    converted = tool.fn_metadata.convert_result(dummy_res)
    assert len(converted.content) == 1
    text = converted.content[0].text
    # content doit être le résumé textuel humain (pas un JSON dump)
    assert text.startswith("Bilan pour SEM1")
    assert not text.startswith("{")
    # structured_content doit contenir l'intégralité des données structurées
    assert converted.structured_content["team"]["nom_equipe"] == "SEM1"
    assert converted.structured_content["summary"]["match_joues"] == 1


@pytest.mark.asyncio
async def test_ffbb_bilan_wrap_output_is_false():
    """Vérifie que ffbb_bilan n'a pas wrap_output=True, évitant l'enveloppe {'result': ...}."""
    from ffbb_mcp.server import mcp

    tool = mcp._tool_manager.get_tool("ffbb_bilan")
    assert tool.fn_metadata.wrap_output is False


@pytest.mark.asyncio
async def test_ffbb_saisons_aliases():
    """Vérifie que chaque saison expose à la fois id/season_id et libelle/label."""
    from ffbb_mcp.services.poule import get_saisons_service

    mock_client = AsyncMock()
    mock_client.get_saisons_async.return_value = [
        {
            "id": 1037,
            "libelle": "Saison 2026-2027",
            "actif": True,
            "debut": "2026-07-01",
            "fin": "2027-06-30",
        }
    ]

    with patch(
        "ffbb_mcp.services.poule.get_client_async", AsyncMock(return_value=mock_client)
    ):
        saisons = await get_saisons_service(active_only=True, force_refresh=True)
        assert len(saisons) > 0
        s = saisons[0]
        assert "id" in s
        assert "season_id" in s
        assert str(s["id"]) == str(s["season_id"])
        assert "libelle" in s
        assert "label" in s
        assert s["libelle"] == s["label"]


@pytest.mark.asyncio
async def test_explain_tiebreak_rules_with_poule_id():
    """Vérifie que explain_tiebreak_rules_service calcule concrètement les égalités d'une poule."""
    from ffbb_mcp.services.regulations import explain_tiebreak_rules_service

    mock_poule = {
        "id": "1001",
        "nom": "Poule A",
        "competition": "Régionale 2",
        "rencontres": [
            {
                "id": "r1",
                "nomEquipe1": "Team Alpha",
                "resultatEquipe1": "75",
                "nomEquipe2": "Team Beta",
                "resultatEquipe2": "70",
                "numeroJournee": "1",
            }
        ],
    }
    mock_classements = [
        {
            "position": 1,
            "equipe": "Team Alpha",
            "points": 2,
            "difference": 5,
            "quotient": 1.07,
        },
        {
            "position": 2,
            "equipe": "Team Beta",
            "points": 2,
            "difference": -5,
            "quotient": 0.93,
        },
    ]

    with (
        patch(
            "ffbb_mcp.services.poule.get_poule_service",
            AsyncMock(return_value=mock_poule),
        ),
        patch(
            "ffbb_mcp.services.poule.ffbb_get_classement_service",
            AsyncMock(return_value=mock_classements),
        ),
    ):
        res = await explain_tiebreak_rules_service(poule_id=1001)

        assert res["poule_id"] == 1001
        assert res["poule"]["nom"] == "Poule A"
        assert len(res["applied_tiebreaks"]) == 1
        group = res["applied_tiebreaks"][0]
        assert group["points"] == 2
        assert group["nombre_equipes"] == 2
        assert group["statut"] == "confrontation_directe_jouee"
        assert (
            "Team Alpha devance Team Beta au point-average particulier"
            in group["explication"]
        )
        assert "1 situation(s) d'égalité" in res["summary"]
        assert "presentation" in res
        assert "short_answer" in res["presentation"]


@pytest.mark.asyncio
async def test_explain_tiebreak_rules_poule_fallback():
    """Vérifie le repli gracieux si les données de poule sont indisponibles."""
    from ffbb_mcp.services.regulations import explain_tiebreak_rules_service

    with patch(
        "ffbb_mcp.services.poule.get_poule_service",
        AsyncMock(side_effect=Exception("Poule introuvable")),
    ):
        res = await explain_tiebreak_rules_service(poule_id=999999)
        assert res["poule_id"] == 999999
        assert "warning" in res["poule"]
        assert res["applied_tiebreaks"] == []
        assert "Article 28" in res["summary"]
