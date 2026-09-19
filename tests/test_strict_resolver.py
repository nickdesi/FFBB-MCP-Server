"""Tests unitaires exhaustifs pour le strict resolver d'équipe FFBB."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ffbb_mcp.envelope import ResponseStatus
from ffbb_mcp.strict_resolver import resolve_team_strict


@pytest.fixture
def sample_teams():
    return [
        {
            "engagement_id": "101",
            "poule_id": "901",
            "competition_id": "501",
            "competition": "NATIONALE MASCULINE 2",
            "competition_type": "DIV",
            "team_label": "SCBA SENIOR 1",
            "nom_equipe": "SCBA SENIOR 1",
            "numero_equipe": 1,
            "categorie": "NM2",
            "season_id": "1037",
        },
        {
            "engagement_id": "102",
            "poule_id": "902",
            "competition_id": "502",
            "competition": "PRE NATIONALE MASCULINE",
            "competition_type": "DIV",
            "team_label": "SCBA SENIOR 2",
            "nom_equipe": "SCBA SENIOR 2",
            "numero_equipe": 2,
            "categorie": "PNM",
            "season_id": "1037",
        },
        {
            "engagement_id": "103",
            "poule_id": "903",
            "competition_id": "503",
            "competition": "ESPOIRS ELITE 2",
            "competition_type": "DIV",
            "team_label": "SCBA ESPOIRS",
            "nom_equipe": "SCBA ESPOIRS",
            "numero_equipe": 1,
            "categorie": "ESPOIRS",
            "season_id": "1037",
        },
        {
            "engagement_id": "104",
            "poule_id": "904",
            "competition_id": "504",
            "competition": "U15 MASCULIN ELITE",
            "competition_type": "DIV",
            "team_label": "SCBA U15M1",
            "nom_equipe": "SCBA U15M1",
            "numero_equipe": 1,
            "categorie": "U15M",
            "season_id": "1037",
        },
    ]


@pytest.mark.asyncio
async def test_unique_engagement_id_resolves_exactly_one_team(
    sample_teams, monkeypatch
):
    """Vérifie qu'un engagement_id unique résout exactement l'équipe associée."""
    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": "9326", "nom": "Stade Clermontois"}], None)
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=sample_teams),
    )

    res = await resolve_team_strict(
        club_name="Stade Clermontois",
        organisme_id="9326",
        engagement_id="101",
        mode="strict",
    )

    assert res.status == ResponseStatus.OK
    assert res.selected is not None
    assert res.selected.get("engagement_id") == "101"
    assert (
        "NATIONALE MASCULINE 2" in (res.selected.get("competition") or "")
        or res.selected.get("categorie") == "NM2"
    )


@pytest.mark.asyncio
async def test_multiple_valid_engagements_return_ambiguous(sample_teams, monkeypatch):
    """Vérifie que plusieurs engagements valides sans discriminant renvoient ambiguous."""
    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": "9326", "nom": "Stade Clermontois"}], None)
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=sample_teams),
    )

    res = await resolve_team_strict(
        club_name="Stade Clermontois",
        organisme_id="9326",
        mode="strict",
    )

    assert res.status == ResponseStatus.AMBIGUOUS
    assert res.selected is None
    assert len(res.candidates) > 1


@pytest.mark.asyncio
async def test_no_team_is_selected_when_resolution_is_ambiguous(
    sample_teams, monkeypatch
):
    """Garantit qu'aucune sélection implicite n'est effectuée en cas d'ambiguïté."""
    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": "9326", "nom": "Stade Clermontois"}], None)
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=sample_teams),
    )

    res = await resolve_team_strict(
        club_name="Stade Clermontois",
        organisme_id="9326",
        mode="strict",
    )

    assert res.selected is None
    assert res.status == ResponseStatus.AMBIGUOUS


@pytest.mark.asyncio
async def test_unknown_category_returns_not_found(sample_teams, monkeypatch):
    """Vérifie qu'une catégorie inconnue retourne not_found sans tenter de fallback."""
    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": "9326", "nom": "Stade Clermontois"}], None)
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=sample_teams),
    )

    res = await resolve_team_strict(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="DIVISION_INEXISTANTE_XYZ",
        mode="strict",
    )

    assert res.status == ResponseStatus.NOT_FOUND
    assert res.selected is None


@pytest.mark.asyncio
async def test_resolver_does_not_fallback_to_another_division(
    sample_teams, monkeypatch
):
    """Garantit formellement l'absence de fallback entre divisions différentes (ex: NM3 vers PNM)."""
    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": "9326", "nom": "Stade Clermontois"}], None)
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=sample_teams),
    )

    res = await resolve_team_strict(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="NM3",
        mode="strict",
    )

    # Le club a NM2, PNM, Espoirs, U15M mais PAS de NM3.
    # Le résolveur DOIT retourner not_found, et JAMAIS sélectionner PNM ou NM2 !
    assert res.status == ResponseStatus.NOT_FOUND
    assert res.selected is None


@pytest.mark.asyncio
async def test_resolver_does_not_fallback_to_another_team_number(
    sample_teams, monkeypatch
):
    """Vérifie qu'une demande pour l'équipe 3 quand seules 1 et 2 existent renvoie not_found."""
    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": "9326", "nom": "Stade Clermontois"}], None)
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=sample_teams),
    )

    res = await resolve_team_strict(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="NM2",
        numero_equipe=3,
        mode="strict",
    )

    assert res.status == ResponseStatus.NOT_FOUND
    assert res.selected is None


@pytest.mark.asyncio
async def test_resolver_does_not_mix_senior_espoir_and_youth_teams(
    sample_teams, monkeypatch
):
    """Vérifie l'étanchéité absolue entre équipes seniors, espoirs et jeunes."""
    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": "9326", "nom": "Stade Clermontois"}], None)
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=sample_teams),
    )

    res_youth = await resolve_team_strict(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="U15M",
        numero_equipe=1,
        mode="strict",
    )
    assert res_youth.status == ResponseStatus.OK
    assert res_youth.selected.get("engagement_id") == "104"
    assert "U15" in (res_youth.selected.get("competition") or "")

    # Demande U18 alors qu'il n'y a que U15 et seniors
    res_u18 = await resolve_team_strict(
        club_name="Stade Clermontois",
        organisme_id="9326",
        categorie="U18M",
        mode="strict",
    )
    assert res_u18.status == ResponseStatus.NOT_FOUND
    assert res_u18.selected is None
