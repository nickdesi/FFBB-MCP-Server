"""Tests de validation et de non-régression pour les correctifs de l'audit de fiabilité FFBB.

Couvre les 5 priorités :
1. Résolution stricte des divisions (cas témoin SCBA 9326 PNM / NM3 / NM3 n°1)
2. Fiabilité réglementaire (topics granulaires, métadonnées de source/vérification, départages)
3. Identité et présentation (niveau PNM régional, label bilan équipe, réserve H2H, U9 mixte)
4. Contrats de sortie et cache (cohérence cache_hit / provenance, documents dans list_regulations)
"""

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.envelope import ResponseStatus
from ffbb_mcp.services.bilan import ffbb_bilan_service
from ffbb_mcp.services.club import ffbb_equipes_club_service
from ffbb_mcp.services.regulations import (
    get_regulation_article_service,
    list_regulations_service,
)
from ffbb_mcp.services.team_resolver import (
    _determine_niveau_label,
    ffbb_find_team_candidates_service,
)
from ffbb_mcp.strict_resolver import resolve_team_strict
from ffbb_mcp.tools.team import ffbb_team_summary

# Fixture témoin SCBA (Stade Clermontois Basket Auvergne)
SCBA_TEAMS = [
    {
        "team_id": "200000005341549",
        "engagement_id": "200000005341549",
        "numero_equipe": "1",
        "team_label": "SEM1",
        "nom_equipe": "STADE CLERMONTOIS BASKET AUVERGNE - 1",
        "categorie": "SE",
        "sexe": "M",
        "competition": "Pré nationale masculine",
        "competition_code": "PNM",
        "competition_type": "DIV",
        "poule_id": "1001",
        "competition_id": "501",
        "niveau": 1,
    },
    {
        "team_id": "200000005341797",
        "engagement_id": "200000005341797",
        "numero_equipe": "2",
        "team_label": "SEM2",
        "nom_equipe": "STADE CLERMONTOIS BASKET AUVERGNE - 2",
        "categorie": "SE",
        "sexe": "M",
        "competition": "Régionale masculine seniors - Division 2",
        "competition_code": "RM2",
        "competition_type": "DIV",
        "poule_id": "1002",
        "competition_id": "502",
        "niveau": 1,
    },
    {
        "team_id": "200000005358168",
        "engagement_id": "200000005358168",
        "numero_equipe": "1",
        "team_label": "U11M1",
        "nom_equipe": "STADE CLERMONTOIS BASKET AUVERGNE - 1",
        "categorie": "U11",
        "sexe": "M",
        "competition": "Départementale masculine U11",
        "competition_code": "DMU11",
        "poule_id": "1003",
        "niveau": 2,
    },
    {
        "team_id": "200000005358169",
        "engagement_id": "200000005358169",
        "numero_equipe": "2",
        "team_label": "U11M2",
        "nom_equipe": "STADE CLERMONTOIS BASKET AUVERGNE - 2",
        "categorie": "U11",
        "sexe": "M",
        "competition": "Départementale masculine U11",
        "competition_code": "DMU11",
        "poule_id": "1004",
        "niveau": 2,
    },
]


# =============================================================================
# PRIORITÉ 1 : RÉSOLUTION STRICTE DES DIVISIONS
# =============================================================================


@pytest.mark.asyncio
async def test_p1_bug_a_pnm_unique_resolution():
    """Bug A : categorie='PNM' doit sélectionner SEM1 sans ambiguïté avec SEM2 (RM2)."""
    # Dans strict_resolver
    res = await resolve_team_strict(
        organisme_id="9326",
        categorie="PNM",
        all_teams=SCBA_TEAMS,
    )
    assert res.status == ResponseStatus.OK
    assert res.selected is not None
    assert res.selected.get("engagement_id") == "200000005341549"
    assert res.selected.get("team_label") == "SEM1"

    # Dans find_team_candidates
    with (
        patch(
            "ffbb_mcp.services.search.resolve_club_and_org",
            return_value=([{"nom": "SCBA", "organisme_id": "9326"}], {}),
        ),
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service", return_value=SCBA_TEAMS
        ),
    ):
        cand_res = await ffbb_find_team_candidates_service(
            organisme_id="9326",
            categorie="PNM",
            include_next_match=False,
        )
        # Doit sélectionner uniquement l'équipe PNM (SEM1) sans ambiguïté avec SEM2
        assert cand_res["status"] in ("ok", "resolved")
        assert len(cand_res["candidates"]) == 1
        assert cand_res["candidates"][0]["team_label"] == "SEM1"


@pytest.mark.asyncio
async def test_p1_bug_b_nm3_not_found_no_compatibles():
    """Bug B : categorie='NM3' doit renvoyer not_found, et non proposer PNM et RM2 comme correspondants."""
    res = await resolve_team_strict(
        organisme_id="9326",
        categorie="NM3",
        all_teams=SCBA_TEAMS,
    )
    assert res.status == ResponseStatus.NOT_FOUND
    assert res.selected is None

    with (
        patch(
            "ffbb_mcp.services.search.resolve_club_and_org",
            return_value=([{"nom": "SCBA", "organisme_id": "9326"}], {}),
        ),
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service", return_value=SCBA_TEAMS
        ),
    ):
        cand_res = await ffbb_find_team_candidates_service(
            organisme_id="9326",
            categorie="NM3",
            include_next_match=False,
        )
        assert cand_res["status"] == "not_found"
        assert len(cand_res["candidates"]) == 0


@pytest.mark.asyncio
async def test_p1_bug_c_nm3_num1_no_substitution():
    """Bug C : categorie='NM3', numero_equipe=1 ne doit JAMAIS substituer SEM1 en PNM."""
    mock_eq_svc = AsyncMock(return_value=SCBA_TEAMS)
    with (
        patch(
            "ffbb_mcp.services.team_resolver._get_search_service",
            return_value=mock_eq_svc,
        ),
        patch(
            "ffbb_mcp.strict_resolver._get_equipes_club_service_fn",
            return_value=mock_eq_svc,
        ),
        patch(
            "ffbb_mcp.strict_resolver._get_resolve_club_and_org_fn",
            return_value=AsyncMock(
                return_value=([{"nom": "SCBA", "organisme_id": "9326"}], {})
            ),
        ),
    ):
        # Dans team_summary
        summary_res = await ffbb_team_summary(
            organisme_id="9326",
            categorie="NM3",
            numero_equipe=1,
            season_id="1037",
        )
        assert summary_res.get("status") == "not_found"
        assert summary_res.get("team") is None

        # Dans strict_resolver direct
        strict_res = await resolve_team_strict(
            organisme_id="9326",
            categorie="NM3",
            numero_equipe=1,
            season_id="1037",
            all_teams=SCBA_TEAMS,
        )
        assert strict_res.status == ResponseStatus.NOT_FOUND
        assert strict_res.selected is None


@pytest.mark.asyncio
async def test_p1_preservation_u11m_ambiguous_and_u11f_not_found():
    """Comportements corrects à préserver : U11M sans numéro -> ambiguous ; U11F introuvable -> not_found."""
    # U11M sans numéro -> ambigu entre U11M1 et U11M2
    res_u11m = await resolve_team_strict(
        organisme_id="9326",
        categorie="U11M",
        all_teams=SCBA_TEAMS,
    )
    assert res_u11m.status == ResponseStatus.AMBIGUOUS
    assert len(res_u11m.candidates) == 2

    # U11F introuvable -> not_found (pas de repli silencieux vers U11M)
    res_u11f = await resolve_team_strict(
        organisme_id="9326",
        categorie="U11F",
        all_teams=SCBA_TEAMS,
    )
    assert res_u11f.status == ResponseStatus.NOT_FOUND
    assert res_u11f.selected is None


# =============================================================================
# PRIORITÉ 2 & 4 : RÉGLEMENTS & INVENTAIRE
# =============================================================================


@pytest.mark.asyncio
async def test_p2_and_p4_list_regulations_contract():
    """L'inventaire réglementaire doit exposer 'documents' comme promis dans sa description."""
    res = await list_regulations_service(season="2026-2027")
    assert "documents" in res
    assert isinstance(res["documents"], list)
    assert len(res["documents"]) > 0
    # Rétrocompatibilité : jurisdictions doit également être présent
    assert "jurisdictions" in res
    doc = res["documents"][0]
    assert "id" in doc
    assert "title" in doc
    assert "organizer" in doc


@pytest.mark.asyncio
async def test_p2_article_metadata_and_granular_topics():
    """Les articles doivent avoir des métadonnées de traçabilité et des topics spécifiques à l'article."""
    res = await get_regulation_article_service(
        document_id="rsg_ffbb_2026_2027",
        article_number="Article 28",
    )
    assert res["found"] is True
    art = res["article"]
    assert "content_nature" in art
    assert "disclaimer" in art
    # L'article 28 (départages) ne doit pas avoir des topics non pertinents comme "terrains" ou "licences"
    assert "departages" in art["topics"]
    assert "licences" not in art["topics"]


# =============================================================================
# PRIORITÉ 3 : IDENTITÉ ET PRÉSENTATION
# =============================================================================


def test_p3_pnm_niveau_regional():
    """La Pré-nationale (PNM) doit être classée 'régional' et non 'national'."""
    assert _determine_niveau_label("Pré nationale masculine", "DIV", 1) == "régional"
    assert _determine_niveau_label("Pre-Nationale Masculine", "DIV", 1) == "régional"
    assert _determine_niveau_label("PNM Poule A", "DIV", 1) == "régional"
    assert _determine_niveau_label("Nationale Masculine 3", "DIV", 0) == "national"


@pytest.mark.asyncio
async def test_p3_bilan_presentation_sem1_not_all_categories():
    """Un bilan ciblé sur SEM1 ne doit pas être présenté comme 'Toutes catégories'."""
    from ffbb_mcp._state import state

    if state.cache_bilan is not None:
        if hasattr(state.cache_bilan, "clear_db"):
            state.cache_bilan.clear_db()
        else:
            state.cache_bilan.clear()

    with (
        patch(
            "ffbb_mcp.services.search.resolve_club_and_org",
            return_value=([{"nom": "SCBA", "organisme_id": "9326"}], {}),
        ),
        patch(
            "ffbb_mcp.services.club.ffbb_equipes_club_service",
            return_value=[SCBA_TEAMS[0]],
        ),
        patch(
            "ffbb_mcp.services.poule.get_poule_service",
            return_value={"id": "1001", "rencontres": [], "classement": []},
        ),
        patch("ffbb_mcp.services.poule.ffbb_get_classement_service", return_value=[]),
    ):
        res = await ffbb_bilan_service(
            organisme_id="9326",
            engagement_id="200000005341549",
            season_id="1037",
            force_refresh=True,
        )
    # La présentation ne doit pas afficher 'Toutes catégories'
    short_ans = res.get("presentation", {}).get("short_answer", "")
    assert "Toutes catégories" not in short_ans
    assert "SEM1" in short_ans or "STADE CLERMONTOIS BASKET AUVERGNE - 1" in short_ans


@pytest.mark.asyncio
async def test_p3_u9_mixte_label_convention():
    """Les équipes mixtes U9 doivent porter un label lisible 'U9X1'/'U9X2' et non 'U91'/'U92'."""
    fake_org_data = {
        "nom": "SCBA",
        "engagements": [
            {
                "id": "9991",
                "numeroEquipe": 1,
                "idCompetition": {
                    "id": "111",
                    "nom": "Départementale mixte U9",
                    "code": "DXU9",
                    "typeCompetition": "DIV",
                    "sexe": "X",
                    "categorie": {"code": "U9", "libelle": "U9"},
                },
            },
            {
                "id": "9992",
                "numeroEquipe": 2,
                "idCompetition": {
                    "id": "111",
                    "nom": "Départementale mixte U9",
                    "code": "DXU9",
                    "typeCompetition": "DIV",
                    "sexe": "MIXTE",
                    "categorie": {"code": "U9", "libelle": "U9"},
                },
            },
        ],
    }
    with patch(
        "ffbb_mcp.services.club.resolve_club_and_org",
        return_value=([{"nom": "SCBA", "organisme_id": "9326"}], fake_org_data),
    ):
        teams = await ffbb_equipes_club_service(
            organisme_id="9326", org_data=fake_org_data
        )
        labels = [t["team_label"] for t in teams]
        assert "U91" not in labels
        assert "U92" not in labels
        assert any(lbl in ("U9X1", "U9 Mixte 1") for lbl in labels)
        assert any(lbl in ("U9X2", "U9 Mixte 2") for lbl in labels)
