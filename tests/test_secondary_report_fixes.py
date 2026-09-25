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
