from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.services import ffbb_last_result_service, ffbb_next_match_service


@pytest.mark.asyncio
async def test_phase_prioritization_next_match():
    # Mocking ffbb_equipes_club_service to return two phases
    equipes = [
        {
            "poule_id": "P1",
            "engagement_id": "E1",
            "phase_label": "Phase 1",
            "niveau": 5,
            "nom_equipe": "Club",
            "numero_equipe": "1",
        },
        {
            "poule_id": "P3",
            "engagement_id": "E3",
            "phase_label": "Phase 3",
            "niveau": 5,
            "nom_equipe": "Club",
            "numero_equipe": "1",
        },
    ]

    # Mocking get_poule_service
    def side_effect(poule_id, **kwargs):
        if poule_id == "P1":
            return {
                "id": "P1",
                "rencontres": [
                    {
                        "id": "M1",
                        "joue": 0,
                        "date": "2026-04-01T10:00:00",
                        "idEngagementEquipe1": "E1",
                        "nomEquipe1": "Club",
                    }
                ],
            }
        if poule_id == "P3":
            return {
                "id": "P3",
                "rencontres": [
                    {
                        "id": "M3",
                        "joue": 0,
                        "date": "2026-10-01T10:00:00",
                        "idEngagementEquipe1": "E3",
                        "nomEquipe1": "Club",
                    }
                ],
            }
        return {"rencontres": []}

    with (
        patch(
            "ffbb_mcp.services.ffbb_equipes_club_service",
            AsyncMock(return_value=equipes),
        ),
        patch(
            "ffbb_mcp.services.get_poule_service", AsyncMock(side_effect=side_effect)
        ),
    ):
        result = await ffbb_next_match_service(
            organisme_id=123, categorie="U11M", numero_equipe=1
        )

        # Should pick Phase 3 (M3) even if Phase 1 (M1) is sooner
        assert result["match"]["match_id"] == "M3"


@pytest.mark.asyncio
async def test_phase_prioritization_last_result():
    equipes = [
        {
            "poule_id": "P1",
            "engagement_id": "E1",
            "phase_label": "Phase 1",
            "niveau": 5,
            "nom_equipe": "Club",
            "numero_equipe": "1",
        },
        {
            "poule_id": "P3",
            "engagement_id": "E3",
            "phase_label": "Phase 3",
            "niveau": 5,
            "nom_equipe": "Club",
            "numero_equipe": "1",
        },
    ]

    def side_effect(poule_id, **kwargs):
        if poule_id == "P1":
            return {
                "id": "P1",
                "rencontres": [
                    {
                        "id": "R1",
                        "joue": 1,
                        "date_rencontre": "2026-01-01T10:00:00",
                        "resultatEquipe1": "50",
                        "resultatEquipe2": "40",
                        "nomEquipe1": "Club",
                    }
                ],
            }
        if poule_id == "P3":
            return {
                "id": "P3",
                "rencontres": [
                    {
                        "id": "R3",
                        "joue": 1,
                        "date_rencontre": "2026-03-01T10:00:00",
                        "resultatEquipe1": "60",
                        "resultatEquipe2": "50",
                        "nomEquipe1": "Club",
                    }
                ],
            }
        return {"rencontres": []}

    with (
        patch(
            "ffbb_mcp.services.ffbb_equipes_club_service",
            AsyncMock(return_value=equipes),
        ),
        patch(
            "ffbb_mcp.services.get_poule_service", AsyncMock(side_effect=side_effect)
        ),
    ):
        result = await ffbb_last_result_service(
            organisme_id=123, categorie="U11M", numero_equipe=1
        )

        # Should pick Phase 3 (R3) result
        assert result["score_domicile"] == "60"
