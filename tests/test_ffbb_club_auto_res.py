from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.server import ffbb_club


def _make_resolve_mock(candidates):
    """Construit un mock de resolve_club_and_org retournant (candidates, None)."""
    return AsyncMock(return_value=(candidates, None))


@pytest.mark.asyncio
async def test_ffbb_club_equipes_auto_resolution():
    """Vérifie que ffbb_club(action='equipes') résout le club par son nom."""

    mock_resolve = _make_resolve_mock(
        [{"organisme_id": 123, "nom": "Stade Clermontois", "code": ""}]
    )
    mock_equipes = AsyncMock(return_value=[{"id": "team1", "nom": "U11M1"}])

    with (
        patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.server.ffbb_equipes_club_service", mock_equipes),
    ):
        # Appel sans organisme_id mais avec club_name
        result = await ffbb_club(
            action="equipes",
            club_name="Stade Clermontois",
            force_refresh=True,
        )

        mock_resolve.assert_called_once_with(
            club_name="Stade Clermontois", organisme_id=None, categorie=None, limit=3
        )
        mock_equipes.assert_called_once_with(
            organisme_id=123,
            filtre=None,
            org_data=None,
            force_refresh=True,
        )
        assert result == [{"id": "team1", "nom": "U11M1"}]

    mock_resolve = _make_resolve_mock(
        [{"organisme_id": 123, "nom": "Stade Clermontois", "code": ""}]
    )
    mock_resolve_poule = AsyncMock(return_value=456)
    mock_classement = AsyncMock(
        return_value=[{"position": 1, "nom": "Stade Clermontois"}]
    )

    with (
        patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve),
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
            poule_id="456",
            force_refresh=False,
            target_organisme_id=123,
            target_num=None,
        )
        assert result == [{"position": 1, "nom": "Stade Clermontois"}]


@pytest.mark.asyncio
async def test_ffbb_club_resolution_failure():
    """Vérifie le message d'erreur si le club n'est pas trouvé."""

    mock_resolve = _make_resolve_mock([])

    with patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve):
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
        patch("ffbb_mcp.server.resolve_club_and_org", _make_resolve_mock([])),
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
    """Le filtre 'U11M' est transmis au service calendrier qui gère
    la résolution + filtrage M/F en interne (plus de pré-résolution)."""

    mock_cal = AsyncMock(return_value=[])

    with patch("ffbb_mcp.server.get_calendrier_club_service", mock_cal):
        result = await ffbb_club(
            action="calendrier",
            club_name="Stade Clermontois",
            filtre="U11M",
            numero_equipe=1,
        )

        # Le service de calendrier doit avoir été appelé avec les params bruts
        mock_cal.assert_called_once()
        call_kwargs = mock_cal.call_args.kwargs
        assert call_kwargs["organisme_id"] is None  # pas de pré-résolution
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

    with patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve):
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


@pytest.mark.asyncio
async def test_ffbb_club_no_ambiguity_when_exact_match_and_ententes():
    """Vérifie que ffbb_club ne déclenche pas d'erreur d'ambiguïté quand il y a
    un match exact et que les autres candidats sont uniquement des ententes (ENT.)."""

    gerzat_candidate = {
        "organisme_id": "9282",
        "nom": "GERZAT BASKET",
        "code": "0063001",
        "ville": "GERZAT",
    }
    entente_1 = {
        "organisme_id": "200000002679118",
        "nom": "ENT. GERZAT / JULES VERNE",
        "code": "",
        "ville": "GERZAT",
    }
    entente_2 = {
        "organisme_id": "200000002678912",
        "nom": "ENT. ROMAGNAT / GERZAT",
        "code": "",
        "ville": "ROMAGNAT",
    }
    mock_resolve = _make_resolve_mock([gerzat_candidate, entente_1, entente_2])
    mock_equipes = AsyncMock(return_value=[{"id": "team_u18", "nom": "U18M1"}])

    with (
        patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.server.ffbb_equipes_club_service", mock_equipes),
    ):
        result = await ffbb_club(action="equipes", club_name="Gerzat Basket")

        # Doit résoudre directement vers l'organisme principal 9282
        assert result == [{"id": "team_u18", "nom": "U18M1"}]
        mock_equipes.assert_called_once_with(
            organisme_id="9282",
            filtre=None,
            org_data=None,
            force_refresh=False,
        )


@pytest.mark.asyncio
async def test_disambiguate_clubs_by_category_unit():
    """Vérifie le comportement unitaire de disambiguate_clubs_by_category."""
    from ffbb_mcp.services.common import disambiguate_clubs_by_category

    sayat = {
        "organisme_id": "200000002677671",
        "nom": "ETOILE DE CHAMALIERES SAYAT",
        "ville": "CHAMALIERES",
    }
    bdf = {
        "organisme_id": "9266",
        "nom": "AS BANQUE DE FRANCE CHAMALIERES",
        "ville": "CHAMALIERES",
    }
    candidates = [sayat, bdf]

    # Cas 1 : Exactement un club possède des équipes dans la catégorie
    async def mock_eq_1(organisme_id, filtre=None, **kwargs):
        if str(organisme_id) == "200000002677671":
            return [{"id": "team_u13", "nom": "U13M1"}]
        return []

    with patch("ffbb_mcp.services.ffbb_equipes_club_service", side_effect=mock_eq_1):
        resolved, teams = await disambiguate_clubs_by_category(
            candidates, categorie="U13M", club_name="Chamaliere"
        )
        assert len(resolved) == 1
        assert resolved[0]["organisme_id"] == "200000002677671"
        assert teams is not None and len(teams) == 1

    # Cas 2 : Deux clubs possèdent des équipes -> liste restreinte sans résolution unique
    async def mock_eq_both(organisme_id, filtre=None, **kwargs):
        return [{"id": f"team_{organisme_id}", "nom": "U13M"}]

    with patch("ffbb_mcp.services.ffbb_equipes_club_service", side_effect=mock_eq_both):
        resolved, teams = await disambiguate_clubs_by_category(
            candidates, categorie="U13M", club_name="Chamaliere"
        )
        assert len(resolved) == 2
        assert teams is None

    # Cas 3 : Aucun club ne possède d'équipe -> candidats préservés
    async def mock_eq_none(organisme_id, filtre=None, **kwargs):
        return []

    with patch("ffbb_mcp.services.ffbb_equipes_club_service", side_effect=mock_eq_none):
        resolved, teams = await disambiguate_clubs_by_category(
            candidates, categorie="U13M", club_name="Chamaliere"
        )
        assert len(resolved) == 2
        assert teams is None


@pytest.mark.asyncio
async def test_ffbb_club_auto_disambiguate_chamaliere_u13m():
    """Vérifie que ffbb_club(action='equipes') lève automatiquement l'ambiguïté
    entre Sayat et Banque de France lorsque filtre='U13M'."""
    sayat = {
        "organisme_id": "200000002677671",
        "nom": "ETOILE DE CHAMALIERES SAYAT",
        "ville": "CHAMALIERES",
        "code_postal": "63400",
        "departement": "Puy-de-dôme",
        "genre": None,
    }
    bdf = {
        "organisme_id": "9266",
        "nom": "AS BANQUE DE FRANCE CHAMALIERES",
        "ville": "CHAMALIERES",
        "code_postal": "63400",
        "departement": "Puy-de-dôme",
        "genre": "M",
    }
    mock_resolve = _make_resolve_mock([sayat, bdf])

    async def mock_equipes_call(organisme_id, filtre=None, **kwargs):
        if str(organisme_id) == "200000002677671":
            return [{"id": "u13_1", "nom": "U13M-1"}]
        return []

    with (
        patch("ffbb_mcp.server.resolve_club_and_org", mock_resolve),
        patch(
            "ffbb_mcp.services.ffbb_equipes_club_service", side_effect=mock_equipes_call
        ),
        patch(
            "ffbb_mcp.server.ffbb_equipes_club_service", side_effect=mock_equipes_call
        ),
    ):
        result = await ffbb_club(
            action="equipes", club_name="Chamaliere", filtre="U13M"
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].get("id") == "u13_1"
        assert result[0].get("nom") == "U13M-1"


@pytest.mark.asyncio
async def test_get_calendrier_club_auto_disambiguate():
    """Vérifie que le service de calendrier lève l'ambiguïté sur un club candidat ayant l'équipe."""
    from ffbb_mcp.services.calendar import get_calendrier_club_service

    sayat = {
        "organisme_id": "200000002677671",
        "nom": "ETOILE DE CHAMALIERES SAYAT",
        "ville": "CHAMALIERES",
    }
    bdf = {
        "organisme_id": "9266",
        "nom": "AS BANQUE DE FRANCE CHAMALIERES",
        "ville": "CHAMALIERES",
    }
    mock_resolve = _make_resolve_mock([sayat, bdf])

    async def mock_eq_call(organisme_id, filtre=None, **kwargs):
        if str(organisme_id) == "200000002677671":
            return [
                {
                    "id": "u13_1",
                    "nom": "U13M-1",
                    "poule_id": "poule_1",
                    "engagement_id": "eng_1",
                }
            ]
        return []

    mock_poule = AsyncMock(
        return_value={
            "id": "poule_1",
            "nom": "Poule A",
            "rencontres": [
                {
                    "id": "m1",
                    "date": "2026-03-20",
                    "idEngagementEquipe1": {"id": "eng_1"},
                    "nomEquipe1": "ETOILE DE CHAMALIERES SAYAT - 1",
                    "nomEquipe2": "ADVERSAIRE",
                }
            ],
        }
    )

    with (
        patch("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.services.ffbb_equipes_club_service", side_effect=mock_eq_call),
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service", side_effect=mock_eq_call
        ),
        patch("ffbb_mcp.services.poule.get_poule_service", mock_poule),
    ):
        result = await get_calendrier_club_service(
            club_name="Chamaliere", categorie="U13M"
        )

        assert "error" not in result
        assert "items" in result
        assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_resolve_team_service_auto_disambiguate_category():
    """Vérifie que ffbb_resolve_team_service lève l'ambiguïté sur Sayat avec categorie='U13M'."""
    from ffbb_mcp.services.search import ffbb_resolve_team_service

    sayat = {
        "organisme_id": "200000002677671",
        "nom": "ETOILE DE CHAMALIERES SAYAT",
        "ville": "CHAMALIERES",
    }
    bdf = {
        "organisme_id": "9266",
        "nom": "AS BANQUE DE FRANCE CHAMALIERES",
        "ville": "CHAMALIERES",
    }
    mock_resolve = _make_resolve_mock([sayat, bdf])

    async def mock_eq_call(organisme_id, filtre=None, **kwargs):
        if str(organisme_id) == "200000002677671":
            return [{"id": "u13_1", "nom": "U13M-1", "poule_id": "poule_1"}]
        return []

    with (
        patch("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.services.ffbb_equipes_club_service", side_effect=mock_eq_call),
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service", side_effect=mock_eq_call
        ),
    ):
        result = await ffbb_resolve_team_service(
            club_name="Chamaliere", categorie="U13M"
        )

        assert result.get("status") == "resolved"
        assert result.get("team") is not None
        assert result["team"]["id"] == "u13_1"
        assert result.get("club_resolu", {}).get("organisme_id") == "200000002677671"


@pytest.mark.asyncio
async def test_resolve_team_equipes_auto_disambiguate_category():
    """Vérifie que _resolve_team_equipes dans club.py lève l'ambiguïté sur Sayat avec categorie='U13M'."""
    from ffbb_mcp.services.club import _resolve_team_equipes

    sayat = {
        "organisme_id": "200000002677671",
        "nom": "ETOILE DE CHAMALIERES SAYAT",
        "ville": "CHAMALIERES",
    }
    bdf = {
        "organisme_id": "9266",
        "nom": "AS BANQUE DE FRANCE CHAMALIERES",
        "ville": "CHAMALIERES",
    }
    mock_resolve = _make_resolve_mock([sayat, bdf])

    async def mock_eq_call(organisme_id, filtre=None, **kwargs):
        if str(organisme_id) == "200000002677671":
            return [{"id": "u13_1", "nom": "U13M-1", "poule_id": "poule_1"}]
        return []

    with (
        patch("ffbb_mcp.services.resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve),
        patch("ffbb_mcp.services.ffbb_equipes_club_service", side_effect=mock_eq_call),
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service", side_effect=mock_eq_call
        ),
    ):
        error, equipes, club_resolu = await _resolve_team_equipes(
            club_name="Chamaliere",
            organisme_id=None,
            numero_equipe=None,
            categorie="U13M",
        )

        assert error is None
        assert equipes is not None
        assert len(equipes) == 1
        assert equipes[0]["id"] == "u13_1"
        assert club_resolu is not None
        assert club_resolu.get("organisme_id") == "200000002677671"
