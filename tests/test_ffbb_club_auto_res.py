from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.server import ffbb_club


@pytest.mark.asyncio
async def test_ffbb_club_equipes_auto_resolution():
    """Vérifie que ffbb_club(action='equipes') résout le club par son nom."""

    # Mock des services
    mock_search = AsyncMock(return_value=[{"id": 123, "nom": "Stade Clermontois"}])
    mock_equipes = AsyncMock(return_value=[{"id": "team1", "nom": "U11M1"}])

    with (
        patch("ffbb_mcp.server.search_organismes_service", mock_search),
        patch("ffbb_mcp.server.ffbb_equipes_club_service", mock_equipes),
    ):
        # Appel sans organisme_id mais avec club_name
        result = await ffbb_club(action="equipes", club_name="Stade Clermontois")

        # Vérifications (limit=3 maintenant pour détecter l'ambiguïté)
        mock_search.assert_called_once_with(nom="Stade Clermontois", limit=3)
        mock_equipes.assert_called_once_with(organisme_id=123, filtre=None)
        assert result == [{"id": "team1", "nom": "U11M1"}]

    mock_search = AsyncMock(return_value=[{"id": 123, "nom": "Stade Clermontois"}])
    mock_resolve_poule = AsyncMock(return_value=456)
    mock_classement = AsyncMock(
        return_value=[{"position": 1, "nom": "Stade Clermontois"}]
    )

    with (
        patch("ffbb_mcp.server.search_organismes_service", mock_search),
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

        # Vérifications
        mock_search.assert_called_once_with(nom="Stade Clermontois", limit=3)
        mock_resolve_poule.assert_called_once_with(123, "U11M", phase_query="Phase 3")
        mock_classement.assert_called_once_with(
            poule_id=456, force_refresh=False, target_organisme_id=123, target_num=None
        )
        assert result == [{"position": 1, "nom": "Stade Clermontois"}]


@pytest.mark.asyncio
async def test_ffbb_club_resolution_failure():
    """Vérifie le message d'erreur si le club n'est pas trouvé."""

    mock_search = AsyncMock(return_value=[])  # Aucun club trouvé

    with patch("ffbb_mcp.server.search_organismes_service", mock_search):
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
            force_refresh=False,
        )
