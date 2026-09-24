from unittest.mock import AsyncMock, MagicMock

import pytest

from ffbb_mcp.envelope import ResponseStatus
from ffbb_mcp.server import ffbb_get
from ffbb_mcp.services import (
    ffbb_find_team_candidates_service,
    ffbb_resolve_team_service,
    get_engagement_service,
    resolve_opponent_from_poule,
    search_organismes_service,
)
from ffbb_mcp.services.common import is_club_match_confident
from ffbb_mcp.strict_resolver import resolve_team_strict


@pytest.fixture
def vichy_u15_teams():
    """JA Vichy avec 2 équipes U15 sans numero_equipe explicite : Régional Brassage et Départementale."""
    return [
        {
            "engagement_id": "200000005347050",
            "team_id": "200000005347050",
            "poule_id": "200000003056282",
            "competition_id": "200000002898061",
            "competition": "RMU15 Brassage",
            "competition_code": "RMU15 Brassage",
            "competition_type": "PLAT",
            "team_label": "U15M",
            "nom_equipe": "JEANNE D'ARC DE VICHY",
            "numero_equipe": "",
            "categorie": "U15",
            "sexe": "M",
            "season_id": "1037",
            "club": "JEANNE D'ARC DE VICHY",
            "organisme_id": "9220",
        },
        {
            "engagement_id": "200000005358356",
            "team_id": "200000005358356",
            "poule_id": "200000003059000",
            "competition_id": "200000002899000",
            "competition": "Départementale masculine U15 - Division 2",
            "competition_code": "DMU15-D2",
            "competition_type": "DIV",
            "team_label": "U15M",
            "nom_equipe": "JEANNE D'ARC DE VICHY",
            "numero_equipe": "",
            "categorie": "U15",
            "sexe": "M",
            "season_id": "1037",
            "club": "JEANNE D'ARC DE VICHY",
            "organisme_id": "9220",
        },
    ]


@pytest.fixture
def sample_poule_rmu15():
    """Données réelles de la poule RMU15 avec classements et rencontres."""
    return {
        "id": "200000003056282",
        "nom": "Poule A",
        "idCompetition": "200000002898061",
        "classements": [
            {
                "id": "200000003056282-1",
                "id_engagement": {
                    "id": "200000005347056",
                    "nom": "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET",
                    "numero_equipe": "",
                },
                "position": 1,
                "points": 2,
                "organisme_id": "10948",
                "organisme_nom": "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET",
            },
            {
                "id": "200000003056282-2",
                "id_engagement": {
                    "id": "200000005347060",
                    "nom": "CLERMONT BASKET",
                    "numero_equipe": "2",
                },
                "position": 2,
                "points": 2,
                "organisme_id": "9283",
                "organisme_nom": "CLERMONT BASKET",
            },
            {
                "id": "200000003056282-3",
                "id_engagement": {
                    "id": "200000005347058",
                    "nom": "IE - FRAISSES-UNIEUX BASKET 42",
                    "numero_equipe": "",
                },
                "position": 3,
                "points": 1,
                "organisme_id": "10978",
                "organisme_nom": "FRAISSES-UNIEUX BASKET 42",
            },
            {
                "id": "200000003056282-4",
                "id_engagement": {
                    "id": "200000005347050",
                    "nom": "JEANNE D'ARC DE VICHY",
                    "numero_equipe": "",
                },
                "position": 4,
                "points": 1,
                "organisme_id": "9220",
                "organisme_nom": "JEANNE D'ARC DE VICHY",
            },
        ],
        "rencontres": [
            {
                "id": "200000014578830",
                "nomEquipe1": "ST JEAN BONNEFONDS AVANT GARDE BASKET",
                "nomEquipe2": "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET",
                "idEngagementEquipe1": None,
                "idEngagementEquipe2": None,
                "date_rencontre": "2026-09-19 13:30:00",
                "resultatEquipe1": "95",
                "resultatEquipe2": "100",
            },
            {
                "id": "200000014578847",
                "nomEquipe1": "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET",
                "nomEquipe2": "JEANNE D'ARC DE VICHY",
                "idEngagementEquipe1": "200000005347056",
                "idEngagementEquipe2": "200000005347050",
                "date_rencontre": "2026-09-27 11:00:00",
                "resultatEquipe1": None,
                "resultatEquipe2": None,
                "joue": 0,
            },
        ],
    }


@pytest.mark.asyncio
async def test_resolve_team_strict_fanion_hierarchy(vichy_u15_teams):
    """Vérifie que resolve_team_strict résout l'équipe fanion par hiérarchie de division."""
    res = await resolve_team_strict(
        all_teams=vichy_u15_teams,
        categorie="U15M1",
        club_name="JEANNE D'ARC DE VICHY",
    )
    assert res.status == ResponseStatus.OK
    assert res.selected is not None
    assert str(res.selected.get("engagement_id")) == "200000005347050"
    assert "fallback_highest_division_as_team_1" in res.match_strategy
    assert res.confidence == 1.0


@pytest.mark.asyncio
async def test_resolve_team_service_fanion_hierarchy(vichy_u15_teams, monkeypatch):
    """Vérifie ffbb_resolve_team_service avec la hiérarchie fanion."""
    monkeypatch.setattr(
        "ffbb_mcp.services.ffbb_equipes_club_service",
        AsyncMock(return_value=vichy_u15_teams),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=vichy_u15_teams),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.search.resolve_club_and_org",
        AsyncMock(
            return_value=(
                [{"organisme_id": "9220", "nom": "JEANNE D'ARC DE VICHY"}],
                None,
            )
        ),
    )

    res = await ffbb_resolve_team_service(organisme_id="9220", categorie="U15M1")
    assert res["status"] == "resolved"
    assert res["team"]["engagement_id"] == "200000005347050"
    assert "fallback_highest_division_as_team_1" in res["resolution"]["match_strategy"]
    assert res["resolution"]["confidence"] == 1.0


@pytest.mark.asyncio
async def test_find_team_candidates_vichy_ranking(vichy_u15_teams, monkeypatch):
    """Vérifie que l'équipe fanion (RMU15) a un score supérieur à l'équipe départementale."""
    monkeypatch.setattr(
        "ffbb_mcp.services.ffbb_equipes_club_service",
        AsyncMock(return_value=vichy_u15_teams),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=vichy_u15_teams),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.search.resolve_club_and_org",
        AsyncMock(
            return_value=(
                [{"organisme_id": "9220", "nom": "JEANNE D'ARC DE VICHY"}],
                None,
            )
        ),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.club._fetch_poule_matches",
        AsyncMock(return_value=[]),
    )

    res = await ffbb_find_team_candidates_service(organisme_id="9220", query="U15M")
    candidates = res.get("candidates", [])
    assert len(candidates) == 2
    top = candidates[0]
    assert str(top.get("engagement_id")) == "200000005347050"
    assert top.get("confidence", 0) > candidates[1].get("confidence", 0)


@pytest.mark.asyncio
async def test_fuzzy_search_andrezieux_loire_sud_basket(mock_client, monkeypatch):
    """Vérifie que la recherche de 'ANDREZIEUX-BOUTHEON LOIRE SUD BASKET' résout l'organisme 10948."""
    fake_org = {
        "id": 10948,
        "nom": "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET",
        "code": "ARA0042016",
        "commune": {"libelle": "ANDREZIEUX-BOUTHEON", "codePostal": "42160"},
    }

    async def mock_directus_search(query: str, limit: int = 20):
        if "ANDREZIEUX" in query.upper() or "ARA0042016" in query.upper():
            return [fake_org]
        return []

    monkeypatch.setattr(
        "ffbb_mcp.services.search._search_organismes_directus",
        mock_directus_search,
    )

    # Recherche par nom
    orgs = await search_organismes_service("ANDREZIEUX-BOUTHEON LOIRE SUD BASKET")
    assert len(orgs) >= 1
    assert str(orgs[0].get("organisme_id") or orgs[0].get("id")) == "10948"

    # Recherche par code
    orgs_code = await search_organismes_service("ARA0042016")
    assert len(orgs_code) >= 1
    assert str(orgs_code[0].get("organisme_id") or orgs_code[0].get("id")) == "10948"


def test_is_club_match_confident():
    """Vérifie le filtre de confiance strict contre les faux positifs."""
    cand_pontoise = {"nom": "PONTOISE ULR BASKET ST JUST ST RAMBERT"}
    assert not is_club_match_confident(
        cand_pontoise, "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET"
    )

    cand_alsb = {"nom": "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET"}
    assert is_club_match_confident(cand_alsb, "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET")
    assert is_club_match_confident(cand_alsb, "ANDREZIEUX")

    # Régression: LA MONNERIE BASKET (JW≈0.83) ne doit PAS passer pour
    # une requête "LA MONTJOIE SAINT DENIS EN VAL" — préfixe partagé "LA MON"
    # mais aucun mot distinctif en commun.
    cand_monnerie = {"nom": "LA MONNERIE BASKET", "code": "ARA0063002"}
    assert not is_club_match_confident(cand_monnerie, "LA MONTJOIE SAINT DENIS EN VAL")

    # Le vrai club Montjoie doit rester confiant
    cand_montjoie = {"nom": "LA MONTJOIE SAINT DENIS EN VAL", "code": "CVL0045078"}
    assert is_club_match_confident(cand_montjoie, "LA MONTJOIE SAINT DENIS EN VAL")


@pytest.mark.asyncio
async def test_get_engagement_service_and_ffbb_get(
    sample_poule_rmu15, monkeypatch, mock_client
):
    """Vérifie get_engagement_service et ffbb_get(type='engagement')."""
    fake_dict = {
        "id": "200000005347050",
        "idOrganisme": "9220",
        "idCompetition": "200000002898061",
        "idPoule": "200000003056282",
        "numeroEquipe": "",
    }
    fake_eng = MagicMock()
    fake_eng.model_dump = MagicMock(return_value=fake_dict)
    for k, v in fake_dict.items():
        setattr(fake_eng, k, v)
    mock_client.get_engagement_async = AsyncMock(return_value=fake_eng)

    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_poule_service",
        AsyncMock(return_value=sample_poule_rmu15),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_organisme_service",
        AsyncMock(
            return_value={
                "id": "9220",
                "nom": "JEANNE D'ARC DE VICHY",
                "code": "ARA0003016",
            }
        ),
    )

    eng = await get_engagement_service("200000005347050", force_refresh=True)
    assert eng.get("id") == "200000005347050"
    assert eng.get("organisme_id") == "9220"
    assert eng.get("poule_id") == "200000003056282"
    assert eng.get("club", {}).get("nom") == "JEANNE D'ARC DE VICHY"
    assert eng.get("total_matchs", 0) == 1

    tool_res = await ffbb_get(
        id="200000005347050", type="engagement", force_refresh=True
    )
    assert tool_res.get("id") == "200000005347050"
    assert tool_res.get("poule_id") == "200000003056282"


def test_resolve_opponent_from_poule_deterministic(sample_poule_rmu15):
    """Vérifie l'Étape 3 ID-first : résolution d'adversaire par classements de poule."""
    # 1. Adversaire exact
    res1 = resolve_opponent_from_poule(
        sample_poule_rmu15, "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET"
    )
    assert res1["status"] == "resolved"
    assert res1["engagement_id"] == "200000005347056"
    assert res1["organisme_id"] == "10948"
    assert res1["confidence"] == 1.0

    # 2. Adversaire avec numéro d'équipe
    res2 = resolve_opponent_from_poule(sample_poule_rmu15, "CLERMONT BASKET - 2")
    assert res2["status"] == "resolved"
    assert res2["engagement_id"] == "200000005347060"
    assert res2["organisme_id"] == "9283"
    assert res2["numero_equipe"] == "2"
    assert res2["confidence"] >= 0.8

    # 3. Adversaire avec préfixe CTC / IE retiré
    res3 = resolve_opponent_from_poule(sample_poule_rmu15, "FRAISSES-UNIEUX BASKET 42")
    assert res3["status"] == "resolved"
    assert res3["engagement_id"] == "200000005347058"
    assert res3["confidence"] >= 0.8

    # 4. Club absent de la poule -> Échec explicite (zéro fallback halluciné)
    res_unknown = resolve_opponent_from_poule(
        sample_poule_rmu15, "CLUB TOTALEMENT INCONNU AUX BATAILLONS"
    )
    assert res_unknown["status"] == "not_found"
    assert res_unknown["resolved_id"] is None
    assert res_unknown["confidence"] == 0.0


def test_resolve_opponent_from_rencontres_when_no_classement():
    """Vérifie la déduction d'organismes depuis les rencontres quand classements est vide."""
    poule_no_ranking = {
        "id": "POULE_999",
        "nom": "Poule sans classement",
        "classements": [],
        "rencontres": [
            {
                "id": "MATCH_1",
                "nomEquipe1": "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET",
                "nomEquipe2": "JEANNE D'ARC DE VICHY",
                "idOrganismeEquipe1": "10948",
                "idOrganismeEquipe2": "9220",
                "idEngagementEquipe1": "ENG_10948",
                "idEngagementEquipe2": "ENG_9220",
            }
        ],
    }
    res = resolve_opponent_from_poule(
        poule_no_ranking, "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET"
    )
    assert res["status"] == "resolved"
    assert res["organisme_id"] == "10948"
    assert res["engagement_id"] == "ENG_10948"
    assert res["confidence"] == 1.0


@pytest.mark.asyncio
async def test_next_match_and_last_result_enrich_opponent(
    sample_poule_rmu15, vichy_u15_teams, monkeypatch
):
    """Vérifie que ffbb_next_match_service et ffbb_last_result_service enrichissent l'adversaire."""
    from ffbb_mcp.services.club import (
        ffbb_last_result_service,
        ffbb_next_match_service,
    )

    monkeypatch.setattr(
        "ffbb_mcp.services.search.resolve_club_and_org",
        AsyncMock(
            return_value=(
                [{"organisme_id": "9220", "nom": "JEANNE D'ARC DE VICHY"}],
                None,
            )
        ),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=vichy_u15_teams),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_poule_service",
        AsyncMock(return_value=sample_poule_rmu15),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.get_poule_service",
        AsyncMock(return_value=sample_poule_rmu15),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.search.get_rencontre_service",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.salle._enrich_with_salle_details",
        AsyncMock(return_value=None),
    )

    # Next match
    next_res = await ffbb_next_match_service(
        organisme_id="9220",
        categorie="U15M1",
    )
    assert next_res["status"] == "ok"
    assert next_res["adversaire_organisme_id"] == "10948"
    assert next_res["adversaire_engagement_id"] == "200000005347056"
    assert next_res["data"]["match"]["opponent"]["organisme_id"] == "10948"
    assert (
        next_res["data"]["match"]["opponent"]["name"]
        == "ANDREZIEUX-BOUTHEON LOIRE SUD BASKET"
    )

    # Last result
    last_poule = dict(sample_poule_rmu15)
    last_poule["rencontres"] = [
        {
            "id": "200000014578800",
            "nomEquipe1": "JEANNE D'ARC DE VICHY",
            "nomEquipe2": "CLERMONT BASKET - 2",
            "idEngagementEquipe1": "200000005347050",
            "idEngagementEquipe2": "200000005347060",
            "date_rencontre": "2026-09-12 15:00:00",
            "resultatEquipe1": "65",
            "resultatEquipe2": "70",
            "joue": 1,
        }
    ]
    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_poule_service",
        AsyncMock(return_value=last_poule),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.get_poule_service",
        AsyncMock(return_value=last_poule),
    )
    last_res = await ffbb_last_result_service(
        organisme_id="9220",
        categorie="U15M1",
    )
    assert last_res["status"] == "ok"
    assert last_res["adversaire_organisme_id"] == "9283"
    assert last_res["adversaire_engagement_id"] == "200000005347060"
    assert last_res["adversaire_numero_equipe"] == "2"


@pytest.mark.asyncio
async def test_cascade_cache_invalidation(mock_client):
    """Vérifie l'invalidation en cascade sur get_poule_service et get_organisme_service."""
    from ffbb_mcp._state import state
    from ffbb_mcp.services.poule import (
        ffbb_get_classement_service,
        get_organisme_service,
        get_poule_service,
    )

    fake_poule = {"id": "123", "classements": [], "rencontres": []}
    fake_org = {"id": 456, "nom": "TEST CLUB", "engagements": []}

    mock_client.get_poule_async.return_value = fake_poule
    mock_client.get_organisme_async.return_value = fake_org

    if state.cache_poule is not None:
        state.cache_poule["poule:123"] = fake_poule
    if state.cache_classement is not None:
        state.cache_classement["classement:123::"] = [{"test": 1}]
    if state.cache_organisme is not None:
        state.cache_organisme["organisme:456"] = fake_org
    if state.cache_equipes is not None:
        state.cache_equipes["equipes:456:all"] = [{"id": 1}]

    # force_refresh sur poule 123 -> purge classement associé
    await get_poule_service("123", force_refresh=True)
    if state.cache_classement is not None:
        assert "classement:123::" not in state.cache_classement

    # force_refresh sur classement 123 -> purge poule associée
    if state.cache_poule is not None:
        state.cache_poule["poule:123"] = fake_poule
    await ffbb_get_classement_service("123", force_refresh=True)
    if state.cache_poule is not None:
        assert "poule:123" not in state.cache_poule

    # force_refresh sur organisme 456 -> purge equipes associées
    await get_organisme_service(456, force_refresh=True)
    if state.cache_equipes is not None:
        assert "equipes:456:all" not in state.cache_equipes


def test_persistent_cache_mapping_methods_and_delete_prefix():
    """Vérifie le respect du protocole Mapping et delete_prefix sur PersistentCache."""
    from ffbb_mcp.persistent_cache import PersistentCache

    inner = {}
    p_cache = PersistentCache(inner, name="test_mapping")
    p_cache["equipes:100:1"] = {"a": 1}
    p_cache["equipes:100:2"] = {"b": 2}
    p_cache["equipes:200:1"] = {"c": 3}

    assert len(p_cache) == 3
    assert set(p_cache.keys()) == {
        "equipes:100:1",
        "equipes:100:2",
        "equipes:200:1",
    }
    assert len(list(p_cache.values())) == 3
    assert len(list(p_cache.items())) == 3
    assert list(iter(p_cache)) == list(p_cache.keys())

    # delete_prefix
    p_cache.delete_prefix("equipes:100:")
    assert len(p_cache) == 1
    assert "equipes:200:1" in p_cache
    assert "equipes:100:1" not in p_cache
    assert "equipes:100:2" not in p_cache
