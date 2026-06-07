from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.server import ffbb_club


def _make_resolve_mock(candidates):
    """Construit un mock de _resolve_club_and_org retournant (candidates, None)."""
    return AsyncMock(return_value=(candidates, None))


@pytest.mark.asyncio
async def test_ffbb_club_equipes_auto_resolution():
    """Vérifie que ffbb_club(action='equipes') résout le club par son nom."""

    mock_resolve = _make_resolve_mock(
        [{"organisme_id": 123, "nom": "Stade Clermontois", "code": ""}]
    )
    mock_equipes = AsyncMock(return_value=[{"id": "team1", "nom": "U11M1"}])

    with (
        patch("ffbb_mcp.server._resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.server.ffbb_equipes_club_service", mock_equipes),
    ):
        # Appel sans organisme_id mais avec club_name
        result = await ffbb_club(action="equipes", club_name="Stade Clermontois")

        mock_resolve.assert_called_once_with(
            club_name="Stade Clermontois", organisme_id=None, categorie=None, limit=3
        )
        mock_equipes.assert_called_once_with(organisme_id=123, filtre=None)
        assert result == [{"id": "team1", "nom": "U11M1"}]

    mock_resolve = _make_resolve_mock(
        [{"organisme_id": 123, "nom": "Stade Clermontois", "code": ""}]
    )
    mock_resolve_poule = AsyncMock(return_value=456)
    mock_classement = AsyncMock(
        return_value=[{"position": 1, "nom": "Stade Clermontois"}]
    )

    with (
        patch("ffbb_mcp.server._resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.server.resolve_poule_id_service", mock_resolve_poule),
        patch("ffbb_mcp.server.ffbb_get_classement_service", mock_classement),
    ):
        # Appel avec club_name + filtre (pour déclencher la résolution de poule)
        result = await ffbb_club(
            action="classement",
            club_name="Stade Clermontois",
            filtre="U11M",
            phase="Phase 3",
        )

        mock_resolve.assert_called_once_with(
            club_name="Stade Clermontois", organisme_id=None, categorie="U11M", limit=3
        )
        mock_resolve_poule.assert_called_once_with(123, "U11M", phase_query="Phase 3")
        mock_classement.assert_called_once_with(
            poule_id=456, force_refresh=False, target_organisme_id=123, target_num=None
        )
        assert result == [{"position": 1, "nom": "Stade Clermontois"}]


@pytest.mark.asyncio
async def test_ffbb_club_resolution_failure():
    """Vérifie le message d'erreur si le club n'est pas trouvé."""

    mock_resolve = _make_resolve_mock([])

    with patch("ffbb_mcp.server._resolve_club_and_org", mock_resolve):
        result = await ffbb_club(action="equipes", club_name="Club Inconnu")

        assert "error" in result[0]
        assert "Aucun club trouvé" in result[0]["error"]


@pytest.mark.asyncio
async def test_ffbb_club_calendrier_with_numero_equipe():
    # Verify that the numero_equipe parameter is properly passed down
    with patch("ffbb_mcp.server.get_calendrier_club_service") as mock_cal_service:
        # Mocking to return an empty list just to test the argument passing
        mock_cal_service.return_value = []

        await ffbb_club(
            action="calendrier",
            club_name="Stade Clermontois",
            organisme_id=123,
            filtre="U11M",
            numero_equipe=1,
        )

        mock_cal_service.assert_called_once_with(
            club_name="Stade Clermontois",
            organisme_id=123,
            categorie="U11M",
            numero_equipe=1,
            adversaire=None,
            force_refresh=False,
        )


@pytest.mark.asyncio
async def test_ffbb_club_calendrier_match_day_does_not_force_refresh():
    with (
        patch("ffbb_mcp.server.get_calendrier_club_service") as mock_cal_service,
        patch("ffbb_mcp.server._resolve_club_and_org", _make_resolve_mock([])),
    ):
        mock_cal_service.return_value = []

        await ffbb_club(
            action="calendrier",
            club_name="Stade Clermontois",
            organisme_id=123,
            filtre="U11M",
            force_refresh=False,
        )

        mock_cal_service.assert_called_once_with(
            club_name="Stade Clermontois",
            organisme_id=123,
            categorie="U11M",
            numero_equipe=None,
            adversaire=None,
            force_refresh=False,
        )


@pytest.mark.asyncio
async def test_ffbb_club_calendrier_filters_by_gender():
    """Le filtre 'U11M' doit sélectionner silencieusement le club AUVERGNE
    (général/masculin) et non déclencher une ambiguïté avec le FEMININ."""

    auv_candidate = {
        "organisme_id": "9326",
        "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
        "code": "0063127",
        "ville": "CLERMONT-FERRAND",
        "code_postal": "63000",
        "departement": "Puy-de-dôme",
        "genre": None,
    }
    # Le mock de _resolve_club_and_org simule le filtrage M/F déjà appliqué.
    mock_resolve = _make_resolve_mock([auv_candidate])
    mock_cal = AsyncMock(return_value=[])

    with (
        patch("ffbb_mcp.server._resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.server.get_calendrier_club_service", mock_cal),
    ):
        result = await ffbb_club(
            action="calendrier",
            club_name="Stade Clermontois",
            filtre="U11M",
            numero_equipe=1,
        )

        # Le service de calendrier doit avoir été appelé avec le bon organisme_id
        mock_cal.assert_called_once()
        call_kwargs = mock_cal.call_args.kwargs
        assert call_kwargs["organisme_id"] == "9326"
        assert call_kwargs["club_name"] == "Stade Clermontois"
        assert call_kwargs["categorie"] == "U11M"
        assert call_kwargs["numero_equipe"] == 1
        # Pas d'erreur d'ambiguïté
        assert isinstance(result, list)
        assert not (result and isinstance(result[0], dict) and "error" in result[0])


@pytest.mark.asyncio
async def test_ffbb_club_ambiguity_includes_ville_genre():
    """Quand l'ambiguïté est réelle (pas de filtre genre), les candidats
    retournés doivent inclure ville, code_postal, departement, genre."""

    fem_candidate = {
        "organisme_id": "9269",
        "nom": "STADE CLERMONTOIS BASKET FEMININ",
        "code": "0063126",
        "ville": "CLERMONT-FERRAND",
        "code_postal": "63000",
        "departement": "Puy-de-dôme",
        "genre": "F",
    }
    auv_candidate = {
        "organisme_id": "9326",
        "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
        "code": "0063127",
        "ville": "CLERMONT-FERRAND",
        "code_postal": "63000",
        "departement": "Puy-de-dôme",
        "genre": None,
    }
    mock_resolve = _make_resolve_mock([auv_candidate, fem_candidate])

    with patch("ffbb_mcp.server._resolve_club_and_org", mock_resolve):
        result = await ffbb_club(action="equipes", club_name="Stade Clermontois")

        assert "error" in result[0]
        assert "Plusieurs clubs" in result[0]["error"]
        cands = result[0]["candidates"]
        assert len(cands) == 2
        for c in cands:
            assert "id" in c
            assert "nom" in c
            assert c.get("ville") == "CLERMONT-FERRAND"
            assert c.get("code_postal") == "63000"
            assert c.get("departement") == "Puy-de-dôme"
            assert "genre" in c
        # Vérifie que le genre est bien discriminé
        by_id = {c["id"]: c for c in cands}
        assert by_id["9269"]["genre"] == "F"
        assert by_id["9326"]["genre"] is None
