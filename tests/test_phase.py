from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ffbb_mcp.services import (
    ffbb_last_result_service,
    ffbb_next_match_service,
    resolve_poule_id_service,
)


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
        patch(
            "ffbb_mcp.services._resolve_club_and_org",
            AsyncMock(return_value=([{"nom": "Club", "organisme_id": "123"}], {})),
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
        patch(
            "ffbb_mcp.services._resolve_club_and_org",
            AsyncMock(return_value=([{"nom": "Club", "organisme_id": "123"}], {})),
        ),
    ):
        result = await ffbb_last_result_service(
            organisme_id=123, categorie="U11M", numero_equipe=1
        )

        # Should pick Phase 3 (R3) result
        assert result["score_domicile"] == "60"


# ---------------------------------------------------------------------------
# Tests for resolve_poule_id_service — phase selection correctness
# Regression test for: "3" in "u13f phase 1" → True (false positive substring match)
# ---------------------------------------------------------------------------

_EQUIPES_U13F = [
    {
        "poule_id": "P1",
        "competition": "U13F Phase 1",
        "phase_label": "Phase 1",
        "niveau": 5,
    },
    {
        "poule_id": "P3",
        "competition": "U13F Phase 3",
        "phase_label": "Phase 3",
        "niveau": 5,
    },
]


@pytest.mark.asyncio
async def test_resolve_poule_id_phase3_not_matching_u13f_phase1():
    """
    Régression : chercher phase='3' sur des équipes U13F ne doit PAS retourner
    la poule de Phase 1 (faux positif '3' in 'u13f phase 1' via sous-chaîne).
    """
    with patch(
        "ffbb_mcp.services.ffbb_equipes_club_service",
        AsyncMock(return_value=_EQUIPES_U13F),
    ):
        result = await resolve_poule_id_service(9269, "U13F", phase_query="3")
        assert result == "P3", f"Attendu 'P3', obtenu '{result}'"


@pytest.mark.asyncio
async def test_resolve_poule_id_phase1_returns_correct_poule():
    """Phase '1' doit retourner P1, pas P3."""
    with patch(
        "ffbb_mcp.services.ffbb_equipes_club_service",
        AsyncMock(return_value=_EQUIPES_U13F),
    ):
        result = await resolve_poule_id_service(9269, "U13F", phase_query="1")
        assert result == "P1", f"Attendu 'P1', obtenu '{result}'"


@pytest.mark.asyncio
async def test_resolve_poule_id_phase_not_found_returns_none():
    """Phase inexistante (ex: '5') → None, pas de sélection silencieuse d'une mauvaise poule."""
    with patch(
        "ffbb_mcp.services.ffbb_equipes_club_service",
        AsyncMock(return_value=_EQUIPES_U13F),
    ):
        result = await resolve_poule_id_service(9269, "U13F", phase_query="5")
        assert result is None


@pytest.mark.asyncio
async def test_resolve_poule_id_no_phase_returns_most_advanced():
    """Sans phase_query, doit retourner la phase la plus avancée (Phase 3 > Phase 1)."""
    with patch(
        "ffbb_mcp.services.ffbb_equipes_club_service",
        AsyncMock(return_value=_EQUIPES_U13F),
    ):
        result = await resolve_poule_id_service(9269, "U13F", phase_query=None)
        assert result == "P3", (
            f"Attendu 'P3' (phase la plus avancée), obtenu '{result}'"
        )


# ---------------------------------------------------------------------------
# Tests — Salle enrichment in next_match and last_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_match_enriches_salle_from_id():
    """ffbb_next_match doit enrichir salle/ville via get_salle quand idSalle est présent."""
    equipes = [
        {
            "poule_id": "P1",
            "engagement_id": "E1",
            "phase_label": "Phase 1",
            "niveau": 5,
            "nom_equipe": "Stade Clermontois",
            "numero_equipe": "1",
        }
    ]

    match_data = {
        "id": "M1",
        "joue": 0,
        "date": "2026-06-01T14:00:00",
        "idEngagementEquipe1": "E1",
        "nomEquipe1": "Stade Clermontois",
        "nomEquipe2": "AS Montferrand",
        "idSalle": "S42",
    }

    salle_data = {
        "id": "S42",
        "nom": "Salle Jean Bouin",
        "ville": "Clermont-Ferrand",
        "adresse": "12 rue du sport",
    }

    salle_mock = MagicMock()
    salle_mock.model_dump = MagicMock(return_value=salle_data)

    client_mock = MagicMock()
    client_mock.get_salle_async = AsyncMock(return_value=salle_mock)

    def poule_side_effect(poule_id, **kwargs):
        return {"id": poule_id, "rencontres": [match_data]}

    with (
        patch(
            "ffbb_mcp.services.ffbb_equipes_club_service",
            AsyncMock(return_value=equipes),
        ),
        patch(
            "ffbb_mcp.services.get_poule_service",
            AsyncMock(side_effect=poule_side_effect),
        ),
        patch(
            "ffbb_mcp.services._resolve_club_and_org",
            AsyncMock(
                return_value=([{"nom": "Stade Clermontois", "organisme_id": "123"}], {})
            ),
        ),
        patch(
            "ffbb_mcp.services.club.get_client_async",
            AsyncMock(return_value=client_mock),
        ),
    ):
        result = await ffbb_next_match_service(
            organisme_id=123, categorie="U11M", numero_equipe=1
        )

        assert result["status"] == "ok"
        assert result["match"]["salle"] == "Salle Jean Bouin"
        assert result["match"]["ville"] == "Clermont-Ferrand"


@pytest.mark.asyncio
async def test_last_result_enriches_salle_from_id():
    """ffbb_last_result doit enrichir salle/ville via get_salle quand idSalle est présent."""
    equipes = [
        {
            "poule_id": "P1",
            "engagement_id": "E1",
            "phase_label": "Phase 1",
            "niveau": 5,
            "nom_equipe": "Stade Clermontois",
            "numero_equipe": "1",
        }
    ]

    match_data = {
        "id": "R1",
        "joue": 1,
        "date_rencontre": "2026-05-15T18:00:00",
        "resultatEquipe1": "75",
        "resultatEquipe2": "68",
        "idEngagementEquipe1": "E1",
        "nomEquipe1": "Stade Clermontois",
        "nomEquipe2": "AS Montferrand",
        "idSalle": "S99",
    }

    salle_data = {
        "id": "S99",
        "nom": "Gymnase des Sports",
        "ville": "Montferrand",
        "adresse": "5 avenue du gymnase",
    }

    salle_mock = MagicMock()
    salle_mock.model_dump = MagicMock(return_value=salle_data)

    client_mock = MagicMock()
    client_mock.get_salle_async = AsyncMock(return_value=salle_mock)

    def poule_side_effect(poule_id, **kwargs):
        return {"id": poule_id, "rencontres": [match_data]}

    with (
        patch(
            "ffbb_mcp.services.ffbb_equipes_club_service",
            AsyncMock(return_value=equipes),
        ),
        patch(
            "ffbb_mcp.services.get_poule_service",
            AsyncMock(side_effect=poule_side_effect),
        ),
        patch(
            "ffbb_mcp.services._resolve_club_and_org",
            AsyncMock(
                return_value=([{"nom": "Stade Clermontois", "organisme_id": "123"}], {})
            ),
        ),
        patch(
            "ffbb_mcp.services.club.get_client_async",
            AsyncMock(return_value=client_mock),
        ),
    ):
        result = await ffbb_last_result_service(
            organisme_id=123, categorie="U11M", numero_equipe=1
        )

        assert result["status"] == "ok"
        assert result["salle"] == "Gymnase des Sports"
        assert result["ville"] == "Montferrand"
