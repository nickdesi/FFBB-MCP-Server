"""Régression : divergence next_match team_summary vs find_team_candidates.

Cas réel : SAINT DENIS US (11781), U13M brassage, engagement 200000005387270.
find_team_candidates trouvait le match (AC Bobigny, 26/09) mais team_summary
invoqué sans `categorie` rendait next_match null (gate `effective_org_id and
categorie`), et les enveloppes d'erreur (ambiguous/...) pouvaient passer pour
des matchs.
"""

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.server import ffbb_team_summary

RESOLVED_U13M = {
    "status": "resolved",
    "team": {
        "team_id": 200000005387270,
        "team_label": "U13M",
        "numero_equipe": "",
        "nom_equipe": "SAINT DENIS UNION SPORTS",
        "competition": "Brassage U13 masculins",
        "engagement_id": "200000005387270",
        "poule_id": "200000003061669",
    },
    "club_resolu": {"organisme_id": 11781, "nom": "SAINT DENIS UNION SPORTS"},
}

BILAN_EMPTY = {
    "bilan_total": {"victoires": 0, "defaites": 0},
    "phase_courante": {"competition": "Brassage U13 masculins"},
}

NEXT_OK = {
    "status": "ok",
    "data": {
        "match": {
            "context_label": "Prochain match programmé",
            "status": "scheduled",
            "date": "2026-09-26",
        }
    },
    "presentation": {"short_answer": "Bobigny vs Saint-Denis le 26/09."},
    "match": {"adversaire": "ATHLETIC CLUB BOBIGNY", "date": "2026-09-26"},
}


def _patch_all(mock_next):
    return (
        patch(
            "ffbb_mcp.server.ffbb_resolve_team_service",
            AsyncMock(return_value=RESOLVED_U13M),
        ),
        patch(
            "ffbb_mcp.server.ffbb_bilan_service",
            AsyncMock(return_value=BILAN_EMPTY),
        ),
        patch(
            "ffbb_mcp.server.ffbb_last_result_service",
            AsyncMock(
                return_value={"status": "not_found", "message": "Aucun match joué."}
            ),
        ),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
    )


@pytest.mark.asyncio
async def test_team_summary_without_categorie_fetches_next_match():
    """Sans `categorie` (engagement seul), next_match doit être remonté."""
    mock_next = AsyncMock(return_value=NEXT_OK)
    patches = _patch_all(mock_next)
    with patches[0], patches[1], patches[2], patches[3]:
        res = await ffbb_team_summary(
            organisme_id=11781,
            engagement_id=200000005387270,
            poule_id=200000003061669,
            force_refresh=True,
        )

    mock_next.assert_awaited_once()
    assert res["next_match"] is not None
    assert res["next_match"].get("adversaire") == "ATHLETIC CLUB BOBIGNY"
    assert "Prochain match" in res["presentation"]["detail_line"]


@pytest.mark.asyncio
async def test_team_summary_drops_ambiguous_next_envelope():
    """Une enveloppe d'erreur next (ambiguous) ne doit pas passer pour un match."""
    mock_next = AsyncMock(
        return_value={
            "status": "ambiguous",
            "message": "Plusieurs engagements existent.",
            "candidates": ["U13M (n°unique)"],
        }
    )
    patches = _patch_all(mock_next)
    with patches[0], patches[1], patches[2], patches[3]:
        res = await ffbb_team_summary(
            organisme_id=11781,
            categorie="U13M",
        )

    assert res["next_match"] is None
    assert res["presentation"]["detail_line"] == "Aucun match récent ou programmé."


@pytest.mark.asyncio
async def test_team_summary_keeps_explicit_no_upcoming_message():
    """Le vide explicite (no_upcoming_match) garde son message, pas un null sec."""
    mock_next = AsyncMock(
        return_value={
            "status": "no_upcoming_match",
            "message": "Aucun match à venir trouvé pour cette équipe.",
            "presentation": {
                "short_answer": "Aucun match à venir trouvé pour cette équipe."
            },
        }
    )
    patches = _patch_all(mock_next)
    with patches[0], patches[1], patches[2], patches[3]:
        res = await ffbb_team_summary(
            organisme_id=11781,
            categorie="U13M",
        )

    assert "Aucun match à venir" in res["presentation"]["detail_line"]
