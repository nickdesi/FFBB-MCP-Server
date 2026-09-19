"""Tests unitaires exhaustifs pour le calendrier scoped et les filtres de compétition."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ffbb_mcp.services.calendar import get_calendrier_club_service


@pytest.fixture
def complex_club_data():
    teams = [
        {
            "engagement_id": "eng_nm2",
            "poule_id": "poule_nm2",
            "competition_id": "comp_nm2",
            "competition": "NATIONALE MASCULINE 2",
            "competition_nom": "NATIONALE MASCULINE 2",
            "competition_type": "DIV",
            "team_label": "SCBA NM2",
            "nom_equipe": "SCBA NM2",
            "numero_equipe": 1,
            "categorie": "NM2",
        },
        {
            "engagement_id": "eng_elite2",
            "poule_id": "poule_elite2",
            "competition_id": "comp_elite2",
            "competition": "ELITE 2",
            "competition_nom": "ELITE 2",
            "competition_type": "DIV",
            "team_label": "SCBA ELITE 2",
            "nom_equipe": "SCBA ELITE 2",
            "numero_equipe": 1,
            "categorie": "ELIT2",
        },
        {
            "engagement_id": "eng_cup",
            "poule_id": "poule_cup",
            "competition_id": "comp_cup",
            "competition": "COUPE DE FRANCE MASCULINE",
            "competition_nom": "COUPE DE FRANCE MASCULINE",
            "competition_type": "COUPE",
            "team_label": "SCBA COUPE",
            "nom_equipe": "SCBA COUPE",
            "numero_equipe": 1,
            "categorie": "NM2",
        },
        {
            "engagement_id": "eng_reserve",
            "poule_id": "poule_pnm",
            "competition_id": "comp_pnm",
            "competition": "PRE NATIONALE MASCULINE",
            "competition_nom": "PRE NATIONALE MASCULINE",
            "competition_type": "DIV",
            "team_label": "SCBA RESERVE PNM",
            "nom_equipe": "SCBA RESERVE PNM",
            "numero_equipe": 2,
            "categorie": "PNM",
        },
        {
            "engagement_id": "eng_friendly",
            "poule_id": "poule_friendly",
            "competition_id": "comp_friendly",
            "competition": "MATCHS AMICAUX SENIORS",
            "competition_nom": "MATCHS AMICAUX SENIORS",
            "competition_type": "AMIC",
            "team_label": "SCBA AMICAL",
            "nom_equipe": "SCBA AMICAL",
            "numero_equipe": 1,
            "categorie": "NM2",
        },
    ]

    poules = {
        "poule_nm2": {
            "id": "poule_nm2",
            "rencontres": [
                {
                    "id": "m_nm2_1",
                    "idEngagementEquipe1": {"id": "eng_nm2"},
                    "idEngagementEquipe2": {"id": "other_1"},
                    "nomEquipe1": "SCBA NM2",
                    "nomEquipe2": "ADVERSAIRE A",
                    "date_rencontre": "2026-10-10 20:00:00",
                    "joue": 0,
                    "competition_nom": "NATIONALE MASCULINE 2",
                }
            ],
        },
        "poule_elite2": {
            "id": "poule_elite2",
            "rencontres": [
                {
                    "id": "m_elite2_1",
                    "idEngagementEquipe1": {"id": "eng_elite2"},
                    "idEngagementEquipe2": {"id": "other_2"},
                    "nomEquipe1": "SCBA ELITE 2",
                    "nomEquipe2": "ADVERSAIRE B",
                    "date_rencontre": "2026-10-11 20:00:00",
                    "joue": 0,
                    "competition_nom": "ELITE 2",
                }
            ],
        },
        "poule_cup": {
            "id": "poule_cup",
            "rencontres": [
                {
                    "id": "m_cup_1",
                    "idEngagementEquipe1": {"id": "eng_cup"},
                    "idEngagementEquipe2": {"id": "other_3"},
                    "nomEquipe1": "SCBA COUPE",
                    "nomEquipe2": "ADVERSAIRE C",
                    "date_rencontre": "2026-10-12 20:00:00",
                    "joue": 0,
                    "competition_nom": "COUPE DE FRANCE MASCULINE",
                }
            ],
        },
        "poule_pnm": {
            "id": "poule_pnm",
            "rencontres": [
                {
                    "id": "m_pnm_1",
                    "idEngagementEquipe1": {"id": "eng_reserve"},
                    "idEngagementEquipe2": {"id": "other_4"},
                    "nomEquipe1": "SCBA RESERVE PNM",
                    "nomEquipe2": "ADVERSAIRE D",
                    "date_rencontre": "2026-10-13 15:00:00",
                    "joue": 0,
                    "competition_nom": "PRE NATIONALE MASCULINE",
                }
            ],
        },
        "poule_friendly": {
            "id": "poule_friendly",
            "rencontres": [
                {
                    "id": "m_friendly_1",
                    "idEngagementEquipe1": {"id": "eng_friendly"},
                    "idEngagementEquipe2": {"id": "other_5"},
                    "nomEquipe1": "SCBA AMICAL",
                    "nomEquipe2": "ADVERSAIRE E",
                    "date_rencontre": "2026-09-01 20:00:00",
                    "joue": 1,
                    "resultatEquipe1": 70,
                    "resultatEquipe2": 65,
                    "competition_nom": "MATCHS AMICAUX SENIORS",
                }
            ],
        },
    }

    return teams, poules


@pytest.fixture(autouse=True)
def setup_mocks(complex_club_data, monkeypatch):
    teams, poules = complex_club_data
    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": "9326", "nom": "Stade Clermontois"}], None)
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.calendar.resolve_club_and_org", mock_resolve, raising=False
    )

    mock_eq = AsyncMock(return_value=teams)
    monkeypatch.setattr("ffbb_mcp.services.club.ffbb_equipes_club_service", mock_eq)
    monkeypatch.setattr("ffbb_mcp.services.ffbb_equipes_club_service", mock_eq)
    monkeypatch.setattr(
        "ffbb_mcp.services.calendar.ffbb_equipes_club_service", mock_eq, raising=False
    )

    mock_poule = AsyncMock(
        side_effect=lambda pid, *args, **kwargs: poules.get(str(pid), {})
    )
    monkeypatch.setattr("ffbb_mcp.services.poule.get_poule_service", mock_poule)
    monkeypatch.setattr("ffbb_mcp.services.get_poule_service", mock_poule)
    monkeypatch.setattr(
        "ffbb_mcp.services.calendar.get_poule_service", mock_poule, raising=False
    )


@pytest.mark.asyncio
async def test_team_scope_returns_only_one_engagement():
    """Vérifie que scope=team retourne uniquement l'engagement ciblé."""
    res = await get_calendrier_club_service(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="NM2",
        numero_equipe=1,
        scope="team",
        force_refresh=True,
    )

    items = res.get("items", [])
    assert len(items) == 1
    assert items[0]["engagement_id"] == "eng_nm2"
    assert "NATIONALE MASCULINE 2" in items[0]["competition_nom"]


@pytest.mark.asyncio
async def test_championship_calendar_does_not_include_cup_by_default():
    """Vérifie que les matchs de coupe sont exclus par défaut dans un calendrier de championnat."""
    res = await get_calendrier_club_service(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="NM2",
        numero_equipe=1,
        force_refresh=True,
    )

    items = res.get("items", [])
    for m in items:
        assert "COUPE" not in m.get("competition_nom", "").upper()


@pytest.mark.asyncio
async def test_calendar_does_not_include_friendlies_by_default():
    """Vérifie que les amicaux sont exclus par défaut d'une requête calendrier."""
    res = await get_calendrier_club_service(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="NM2",
        numero_equipe=1,
        force_refresh=True,
    )

    items = res.get("items", [])
    for m in items:
        assert "AMICAL" not in m.get("competition_nom", "").upper()


@pytest.mark.asyncio
async def test_calendar_does_not_include_reserves_by_default():
    """Vérifie que l'équipe 1 n'inclut pas les matchs de l'équipe 2 (réserve)."""
    res = await get_calendrier_club_service(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="NM2",
        numero_equipe=1,
        include_reserves=False,
        force_refresh=True,
    )

    items = res.get("items", [])
    for m in items:
        assert m.get("numero_equipe") != 2
        assert "PRE NATIONALE" not in m.get("competition_nom", "").upper()


@pytest.mark.asyncio
async def test_unknown_requested_division_does_not_expand_to_full_club_calendar():
    """Garantit qu'une division non trouvée retourne not_found et jamais le calendrier complet du club."""
    res = await get_calendrier_club_service(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="NM3",  # Le club n'a pas de NM3
        numero_equipe=1,
        force_refresh=True,
    )

    # Interdiction formelle d'élargir silencieusement à NM2 ou PNM
    assert res.get("status") == "not_found"
    assert res.get("items") == [] or res.get("items") is None


@pytest.mark.asyncio
async def test_calendar_response_identifies_every_match_engagement_and_competition():
    """Vérifie que chaque match retourné porte engagement_id, competition_id et team_label."""
    res = await get_calendrier_club_service(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="NM2",
        numero_equipe=1,
        force_refresh=True,
    )

    items = res.get("items", [])
    assert len(items) > 0
    for m in items:
        assert m.get("engagement_id") is not None
        assert m.get("competition_id") is not None
        assert m.get("team_label") is not None
        assert m.get("canonical_status") is not None
        assert m.get("data_quality") is not None
