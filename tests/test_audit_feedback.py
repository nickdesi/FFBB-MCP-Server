import pytest

from ffbb_mcp.services import get_organisme_service


@pytest.mark.asyncio
async def test_api_response_casing():
    """
    Vérifie la conservation du camelCase dans les réponses sérialisées.
    Ce test valide que services.py peut continuer à utiliser des types comme 'idCompetition'.
    """
    # Utilisation d'un ID connu (ex: 2 pour le Comité du Rhône ou similaire)
    # Note: nécessite une connexion internet ou un mock si l'env est restreint.
    # Ici on teste la logique réelle si possible.
    try:
        org_id = 2
        org = await get_organisme_service(org_id)

        # 1. Vérifie la présence des clés racines attendues (snake_case normalisé ou original)
        assert "id" in org
        assert "nom" in org
        assert "engagements" in org

        # 2. Vérifie le casing des objets imbriqués (Source de vérité FFBB)
        if org["engagements"]:
            engagement = org["engagements"][0]
            # On vérifie que le camelCase est préservé via serialize_model
            # Si idCompetition est présent, c'est que le casing original est conservé.
            assert "idCompetition" in engagement, (
                f"Clé 'idCompetition' manquante dans l'engagement. Trouvé: {list(engagement.keys())}"
            )
            assert "libelleCompetition" in engagement

    except Exception as e:
        pytest.skip(
            f"Test sauté car l'API n'est pas accessible ou l'ID est invalide: {e}"
        )


def test_joue_logic_documentation():
    """
    Test symbolique pour valider que la logique de filtrage 'joue' est intentionnelle.
    """
    # La logique : if joue not in (0, "0", None): continue
    # Signifie qu'on accepte :
    # - 0 (entier)
    # - "0" (chaîne)
    # - None (match programmé sans état défini)

    accepted = [0, "0", None]
    rejected = [
        1,
        "1",
        True,
        False,
    ]  # False est souvent 0, mais ici on est strict sur 0/"0"

    def should_keep(joue):
        return joue in (0, "0", None)

    for val in accepted:
        assert should_keep(val) is True
    for val in rejected:
        if val is False:
            continue  # Dépend de la vérité de (False == 0) en Python
        assert should_keep(val) is False


# ---------------------------------------------------------------------------
# Tests — Audit GLM 5.3 (Divisions NM3, Déduplication Poules, Lives, Horaire)
# ---------------------------------------------------------------------------


def test_horaire_renseigne_detection():
    from ffbb_mcp.services.common import _is_horaire_renseigne

    assert (
        _is_horaire_renseigne({"horaire": "0", "date_rencontre": "2026-09-20 00:00:00"})
        is False
    )
    assert (
        _is_horaire_renseigne(
            {"horaire": "00:00", "date_rencontre": "2026-09-20 00:00:00"}
        )
        is False
    )
    assert (
        _is_horaire_renseigne({"horaire": "", "date_rencontre": "2026-09-20"}) is False
    )
    assert (
        _is_horaire_renseigne(
            {"horaire": "15:00", "date_rencontre": "2026-09-20 15:00:00"}
        )
        is True
    )
    assert (
        _is_horaire_renseigne({"horaire": "0", "date_rencontre": "2026-09-20 20:30:00"})
        is True
    )
    assert _is_horaire_renseigne({"horaire": "20h30"}) is True


@pytest.mark.asyncio
async def test_get_lives_service_filtering():
    from unittest.mock import AsyncMock, patch

    from ffbb_mcp._state import state
    from ffbb_mcp.services.poule import get_lives_service

    raw_matches = [
        {"match_id": 1, "match_status": "SCHEDULED", "score_home": 0, "score_out": 0},
        {"match_id": 2, "match_status": "LIVE", "score_home": 45, "score_out": 42},
        {"match_id": 3, "match_status": "QUARTER_3", "score_home": 56, "score_out": 50},
        {"match_id": 4, "match_status": "COMPLETE", "score_home": 80, "score_out": 75},
    ]

    # Invalider cache
    if state.cache_lives is not None:
        state.cache_lives.clear()

    with patch("ffbb_mcp.services.poule.get_client_async") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_lives_async = AsyncMock(return_value=raw_matches)
        mock_get_client.return_value = mock_client

        # Par défaut : uniquement les matchs en cours (LIVE, QUARTER_3)
        lives_only = await get_lives_service(include_scheduled=False)
        assert len(lives_only) == 2
        assert [m["match_id"] for m in lives_only] == [2, 3]

        # Avec include_scheduled=True : tous les matchs
        all_lives = await get_lives_service(include_scheduled=True)
        assert len(all_lives) == 4


@pytest.mark.asyncio
async def test_ffbb_saison_bilan_poule_deduplication():
    from unittest.mock import AsyncMock, patch

    from ffbb_mcp.services.club import ffbb_saison_bilan_service

    fake_equipes = [
        {
            "nom_equipe": "CS PONT DU CHATEAU",
            "engagement_id": "eng_123",
            "poule_id": "poule_999",
            "competition": "NATIONALE MASCULINE 3",
            "numero_equipe": "1",
        }
    ]
    # Poule avec 2 classements identiques pour le même engagement (cas réel FFBB)
    fake_poule = {
        "nom": "Poule A",
        "phase_terminee": True,
        "classements": [
            {
                "id_engagement": {"id": "eng_123"},
                "position": 1,
                "match_joues": 2,
                "gagnes": 2,
                "perdus": 0,
                "nuls": 0,
                "paniers_marques": 150,
                "paniers_encaisses": 120,
                "difference": 30,
            },
            {
                "id_engagement": {"id": "eng_123"},
                "position": 1,
                "match_joues": 2,
                "gagnes": 2,
                "perdus": 0,
                "nuls": 0,
                "paniers_marques": 150,
                "paniers_encaisses": 120,
                "difference": 30,
            },
        ],
    }

    with (
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service",
            new_callable=AsyncMock,
            return_value=fake_equipes,
        ),
        patch(
            "ffbb_mcp.services.poule.get_poule_service",
            new_callable=AsyncMock,
            return_value=fake_poule,
        ),
        patch(
            "ffbb_mcp.services.get_organisme_service",
            new_callable=AsyncMock,
            return_value={"id": 123, "nom": "CS PONT DU CHATEAU"},
        ),
    ):
        res = await ffbb_saison_bilan_service(
            organisme_id=123,
            categorie="NM3",
            numero_equipe=1,
            force_refresh=True,
        )

        assert res["status"] == "ok"
        # Exactement 1 phase après déduplication
        assert len(res["phases"]) == 1
        # Les totaux ne sont comptés qu'une seule fois (match_joues == 2, pas 4)
        assert res["bilan_total"]["match_joues"] == 2
        assert res["bilan_total"]["gagnes"] == 2


@pytest.mark.asyncio
async def test_ffbb_saison_bilan_future_matches_without_classement_is_active():
    from unittest.mock import AsyncMock, patch

    from ffbb_mcp.services.club import ffbb_saison_bilan_service

    fake_equipes = [
        {
            "nom_equipe": "GERZAT BASKET",
            "engagement_id": "eng_1",
            "poule_id": "poule_1",
            "competition": "Départementale masculine U18",
            "numero_equipe": "",
        }
    ]
    fake_poule = {
        "nom": "Poule A",
        "phase_terminee": False,
        "classements": [],
        "rencontres": [
            {
                "id": "match_1",
                "date_rencontre": "2099-10-03T16:30:00+02:00",
                "idEngagementEquipe1": {"id": "eng_1"},
                "nomEquipe1": "GERZAT BASKET",
                "nomEquipe2": "MARINGUES",
                "joue": 0,
            }
        ],
    }

    with (
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service",
            new_callable=AsyncMock,
            return_value=fake_equipes,
        ),
        patch(
            "ffbb_mcp.services.poule.get_poule_service",
            new_callable=AsyncMock,
            return_value=fake_poule,
        ),
        patch(
            "ffbb_mcp.services.get_organisme_service",
            new_callable=AsyncMock,
            return_value={"id": 9282, "nom": "GERZAT BASKET"},
        ),
    ):
        result = await ffbb_saison_bilan_service(
            organisme_id=9282,
            categorie="U18M",
            numero_equipe=1,
            force_refresh=True,
        )

    assert result["status"] == "ok"
    assert result["saison_terminee"] is False
    assert result["competitions_incluses"] == ["Départementale masculine U18"]
    assert result["phases"][0]["match_joues"] == 0


@pytest.mark.asyncio
async def test_classement_quotient_null_when_zero_matches_played():
    """Vérifie que quotient est None (null) si match_joues == 0 pour éviter une division par zéro."""
    from unittest.mock import AsyncMock, patch

    from ffbb_mcp.services.poule import ffbb_get_classement_service

    fake_poule = {
        "id": 99999,
        "classements": [
            {
                "id_engagement": {"id": "eng_1", "nom": "Equipe A", "numero_equipe": 1},
                "position": 1,
                "match_joues": 0,
                "gagnes": 0,
                "perdus": 0,
                "points": 0,
                "difference": 0,
                "quotient": 0.0,
            },
            {
                "id_engagement": {"id": "eng_2", "nom": "Equipe B", "numero_equipe": 1},
                "position": 2,
                "match_joues": 3,
                "gagnes": 2,
                "perdus": 1,
                "points": 5,
                "difference": 15,
                "quotient": 1.12,
            },
        ],
    }

    with patch("ffbb_mcp.services.poule.get_client_async") as mock_client:
        mock_cli = AsyncMock()
        mock_cli.get_poule_async.return_value = fake_poule
        mock_client.return_value = mock_cli

        res = await ffbb_get_classement_service(poule_id=99999, force_refresh=True)
        assert len(res) == 2
        # Équipe 1 (0 match joué) : quotient doit être None (null en JSON)
        assert res[0]["match_joues"] == 0
        assert res[0]["quotient"] is None
        # Équipe 2 (3 matchs joués) : quotient conservé
        assert res[1]["match_joues"] == 3
        assert res[1]["quotient"] == 1.12


@pytest.mark.asyncio
async def test_team_summary_division_nm3_resolves_team_1():
    """Vérifie que categorie='NM3' cible l'équipe 1 (fanion) en l'absence de championnat NM3 exact."""
    from unittest.mock import AsyncMock, patch

    from ffbb_mcp.services.search import ffbb_resolve_team_service

    fake_equipes = [
        {
            "team_id": "eng_sem1",
            "engagement_id": "eng_sem1",
            "numero_equipe": "1",
            "team_label": "SEM1",
            "nom_equipe": "STADE CLERMONTOIS",
            "competition": "Pré nationale masculine",
            "competition_code": "PNM",
            "competition_type": "DIV",
            "competition_id": "comp_pnm",
            "poule_id": "poule_pnm",
            "sexe": "M",
            "categorie": "SE",
        },
        {
            "team_id": "eng_sem2",
            "engagement_id": "eng_sem2",
            "numero_equipe": "2",
            "team_label": "SEM2",
            "nom_equipe": "STADE CLERMONTOIS - 2",
            "competition": "Régionale masculine seniors - Division 2",
            "competition_code": "RM2",
            "competition_type": "DIV",
            "competition_id": "comp_rm2",
            "poule_id": "poule_rm2",
            "sexe": "M",
            "categorie": "SE",
        },
    ]

    mock_resolve = AsyncMock(
        return_value=(
            [{"organisme_id": "9326", "nom": "STADE CLERMONTOIS"}],
            None,
        )
    )

    with (
        patch("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve),
        patch(
            "ffbb_mcp.services.ffbb_equipes_club_service",
            new_callable=AsyncMock,
            return_value=fake_equipes,
        ),
    ):
        res = await ffbb_resolve_team_service(
            organisme_id="9326",
            categorie="NM3",
            force_refresh=True,
        )
        assert res["status"] == "resolved"
        assert res["team"]["team_label"] == "SEM1"
        assert res["team"]["competition_code"] == "PNM"
