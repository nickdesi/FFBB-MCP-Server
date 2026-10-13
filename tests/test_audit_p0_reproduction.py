"""Tests de reproduction pour l'audit fonctionnel FFBB MCP (P0).

Ces tests utilisent les fixtures figées de l'audit (Stade Clermontois U13M2, saison 1037)
pour reproduire rigoureusement les deux anomalies bloquantes P0 :
1. P0-1: Pagination du calendrier avec cache actif.
2. P0-2: Faux négatif de ffbb_last_result par engagement seul / club + engagement.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ffbb_mcp._state import reset_service_state
from ffbb_mcp.tools.club import ffbb_club
from ffbb_mcp.tools.team import ffbb_last_result

# ---------------------------------------------------------------------------
# Fixtures figées issues de l'audit (Stade Clermontois Basket Auvergne U13M)
# ---------------------------------------------------------------------------


@pytest.fixture
def u13m_audit_fixtures():
    org_id = "9326"
    season_id = "1037"
    eng_u13m2 = "200000005358458"
    poule_u13m2 = "200000003057825"
    comp_u13m2 = "200000002898785"

    eng_u13m1 = "200000005363765"
    poule_u13m1 = "200000003058528"
    comp_u13m1 = "200000002899050"

    org_data = {
        "id": int(org_id),
        "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
        "code": "ARA0063074",
        "commune": {
            "libelle": "CLERMONT-FERRAND",
            "codePostal": "63000",
            "departement": "63",
        },
        "engagements": [
            {
                "id": eng_u13m2,
                "numeroEquipe": "2",
                "phase": "Poule Haute 2",
                "idCompetition": {
                    "id": comp_u13m2,
                    "nom": "Départementale masculine U13",
                    "code": "DMU13",
                    "typeCompetition": "DIV",
                    "sexe": "M",
                    "categorie": {"code": "U13"},
                    "saison": {"id": season_id},
                },
                "idPoule": {"id": poule_u13m2},
            },
            {
                "id": eng_u13m1,
                "numeroEquipe": "1",
                "phase": "Division 10",
                "idCompetition": {
                    "id": comp_u13m1,
                    "nom": "Départementale masculine U13 - Division 10",
                    "code": "DMU13-10",
                    "typeCompetition": "DIV",
                    "sexe": "M",
                    "categorie": {"code": "U13"},
                    "saison": {"id": season_id},
                },
                "idPoule": {"id": poule_u13m1},
            },
        ],
    }

    # 3 Matchs de référence pour U13M2
    matches_u13m2 = [
        {
            "id": "200000014753740",
            "numero": "1",
            "numeroJournee": "1",
            "idPoule": poule_u13m2,
            "competitionId": comp_u13m2,
            "competition": "Départementale masculine U13",
            "nomEquipe1": "STADE CLERMONTOIS BASKET AUVERGNE - 2",
            "nomEquipe2": "US BEAUMONT",
            "resultatEquipe1": "74",
            "resultatEquipe2": "31",
            "joue": 1,
            "date_rencontre": "2026-09-27T14:00:00+02:00",
            "idEngagementEquipe1": {"id": eng_u13m2, "numeroEquipe": "2"},
            "idEngagementEquipe2": {"id": "other_1"},
        },
        {
            "id": "200000014753766",
            "numero": "2",
            "numeroJournee": "2",
            "idPoule": poule_u13m2,
            "competitionId": comp_u13m2,
            "competition": "Départementale masculine U13",
            "nomEquipe1": "NOHANENT PUY VALEIX",
            "nomEquipe2": "STADE CLERMONTOIS BASKET AUVERGNE - 2",
            "resultatEquipe1": "52",
            "resultatEquipe2": "56",
            "joue": 1,
            "date_rencontre": "2026-10-03T14:00:00+02:00",
            "idEngagementEquipe1": {"id": "other_2"},
            "idEngagementEquipe2": {"id": eng_u13m2, "numeroEquipe": "2"},
        },
        {
            "id": "200000014753792",
            "numero": "3",
            "numeroJournee": "3",
            "idPoule": poule_u13m2,
            "competitionId": comp_u13m2,
            "competition": "Départementale masculine U13",
            "nomEquipe1": "STADE CLERMONTOIS BASKET AUVERGNE - 2",
            "nomEquipe2": "ETOILE DE CHAMALIERES SAYAT - 2",
            "resultatEquipe1": "137",
            "resultatEquipe2": "6",
            "joue": 1,
            "date_rencontre": "2026-10-10T13:30:00+02:00",
            "idEngagementEquipe1": {"id": eng_u13m2, "numeroEquipe": "2"},
            "idEngagementEquipe2": {"id": "other_3"},
        },
    ]

    poule_u13m2_data = {
        "id": poule_u13m2,
        "nom": "Poule Haute 2",
        "libelle": "Poule Haute 2",
        "competition": "Départementale masculine U13",
        "rencontres": matches_u13m2,
        "classements": [
            {
                "position": 1,
                "points": 6,
                "joues": 3,
                "victoires": 3,
                "defaites": 0,
                "panier_marques": 267,
                "panier_encaisses": 89,
                "difference": 178,
                "id_engagement": {
                    "id": eng_u13m2,
                    "nom": "STADE CLERMONTOIS BASKET AUVERGNE",
                    "numero_equipe": "2",
                },
            }
        ],
    }

    return {
        "org_id": org_id,
        "season_id": season_id,
        "eng_u13m2": eng_u13m2,
        "poule_u13m2": poule_u13m2,
        "comp_u13m2": comp_u13m2,
        "org_data": org_data,
        "poule_u13m2_data": poule_u13m2_data,
        "matches_u13m2": matches_u13m2,
    }


# ---------------------------------------------------------------------------
# P0-1 : Pagination du calendrier avec cache actif
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calendar_pagination_with_active_cache(u13m_audit_fixtures):
    """Vérifie que la page 2 ne renvoie PAS la page 1 lorsque le cache calendrier est actif."""
    reset_service_state()
    f = u13m_audit_fixtures

    with (
        patch("ffbb_mcp.services.search.resolve_club_and_org") as mock_res,
        patch("ffbb_mcp.services.poule.get_organisme_service") as mock_org,
        patch("ffbb_mcp.services.poule.get_poule_service") as mock_poule,
    ):
        mock_res.return_value = (
            [
                {
                    "organisme_id": f["org_id"],
                    "nom": f["org_data"]["nom"],
                    "code": f["org_data"]["code"],
                    "ville": "CLERMONT-FERRAND",
                }
            ],
            f["org_data"],
        )
        mock_org.return_value = f["org_data"]
        mock_poule.return_value = f["poule_u13m2_data"]

        # Étape A: Page 1 (limit=2, offset=0, force_refresh=True)
        page1 = await ffbb_club(
            action="calendrier",
            organisme_id=f["org_id"],
            engagement_id=f["eng_u13m2"],
            season_id=f["season_id"],
            date_debut="2026-09-01",
            date_fin="2026-10-31",
            limit=2,
            offset=0,
            scope="team",
            force_refresh=True,
        )

        assert page1.get("status") != "error"
        assert len(page1["items"]) == 2
        assert page1["items"][0]["id"] == "200000014753740"
        assert page1["items"][1]["id"] == "200000014753766"
        assert page1["_meta"]["total"] == 3
        assert page1["_meta"]["returned"] == 2
        assert page1["_meta"]["offset"] == 0
        assert page1["_meta"]["has_more"] is True
        assert page1["_meta"]["next_offset"] == 2

        # Étape B: Page 2 (limit=2, offset=2, force_refresh=False) -> DOIT RENVOYER LA PAGE 2, PAS LA PAGE 1 !
        page2 = await ffbb_club(
            action="calendrier",
            organisme_id=f["org_id"],
            engagement_id=f["eng_u13m2"],
            season_id=f["season_id"],
            date_debut="2026-09-01",
            date_fin="2026-10-31",
            limit=2,
            offset=2,
            scope="team",
            force_refresh=False,
        )

        assert page2.get("status") != "error"
        assert len(page2["items"]) == 1, (
            f"Page 2 avec cache actif a retourné {len(page2['items'])} éléments au lieu de 1 !"
        )
        assert page2["items"][0]["id"] == "200000014753792"
        assert page2["_meta"]["offset"] == 2
        assert page2["_meta"]["returned"] == 1
        assert page2["_meta"]["total"] == 3
        assert page2["_meta"]["has_more"] is False
        assert "next_offset" not in page2["_meta"]

        # Étape C: Offset hors limites (offset=10)
        page_empty = await ffbb_club(
            action="calendrier",
            organisme_id=f["org_id"],
            engagement_id=f["eng_u13m2"],
            season_id=f["season_id"],
            limit=2,
            offset=10,
            scope="team",
            force_refresh=False,
        )
        assert len(page_empty["items"]) == 0
        assert page_empty["_meta"]["offset"] == 10
        assert page_empty["_meta"]["returned"] == 0
        assert page_empty["_meta"]["has_more"] is False


# ---------------------------------------------------------------------------
# P0-2 : Faux négatif de ffbb_last_result par engagement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_result_reproduction_variants(u13m_audit_fixtures):
    """Teste séparément les 8 variantes de discriminants demandées par l'audit."""
    reset_service_state()
    f = u13m_audit_fixtures

    with (
        patch("ffbb_mcp.services.search.resolve_club_and_org") as mock_res,
        patch("ffbb_mcp.services.poule.get_organisme_service") as mock_org,
        patch("ffbb_mcp.services.poule.get_poule_service") as mock_poule,
        patch("ffbb_mcp.services.common.resolve_engagement_refs") as mock_eng_refs,
    ):
        mock_res.return_value = (
            [
                {
                    "organisme_id": f["org_id"],
                    "nom": f["org_data"]["nom"],
                    "code": f["org_data"]["code"],
                    "ville": "CLERMONT-FERRAND",
                }
            ],
            f["org_data"],
        )
        mock_org.return_value = f["org_data"]
        mock_poule.return_value = f["poule_u13m2_data"]
        mock_eng_refs.return_value = {
            "organisme_id": f["org_id"],
            "poule_id": f["poule_u13m2"],
            "competition_id": f["comp_u13m2"],
            "numero_equipe": 2,
        }

        # 1. Engagement seul
        res_eng_only = await ffbb_last_result(
            engagement_id=f["eng_u13m2"],
            force_refresh=True,
        )
        assert res_eng_only.get("status") == "ok", (
            f"Variante 1 (engagement seul) a échoué: {res_eng_only}"
        )
        assert res_eng_only.get("data", {}).get("match_id") == "200000014753792"

        # 2. Club + engagement
        res_club_eng = await ffbb_last_result(
            organisme_id=f["org_id"],
            engagement_id=f["eng_u13m2"],
            force_refresh=True,
        )
        assert res_club_eng.get("status") == "ok", (
            f"Variante 2 (club + engagement) a échoué: {res_club_eng}"
        )
        assert res_club_eng.get("data", {}).get("match_id") == "200000014753792"

        # 3. Club + engagement + saison (Reproduction A de l'audit)
        res_a = await ffbb_last_result(
            organisme_id=f["org_id"],
            engagement_id=f["eng_u13m2"],
            season_id=f["season_id"],
            force_refresh=True,
        )
        assert res_a.get("status") == "ok", (
            f"Variante 3 (Reproduction A audit) a échoué: {res_a}"
        )
        assert res_a.get("data", {}).get("match_id") == "200000014753792"

        # 4. Ajout de catégorie uniquement (+ categorie="U13M")
        res_cat = await ffbb_last_result(
            organisme_id=f["org_id"],
            engagement_id=f["eng_u13m2"],
            season_id=f["season_id"],
            categorie="U13M",
            force_refresh=True,
        )
        assert res_cat.get("status") == "ok", (
            f"Variante 4 (+ catégorie) a échoué: {res_cat}"
        )
        assert res_cat.get("data", {}).get("match_id") == "200000014753792"

        # 5. Ajout de numéro uniquement (+ numero_equipe=2)
        res_num = await ffbb_last_result(
            organisme_id=f["org_id"],
            engagement_id=f["eng_u13m2"],
            season_id=f["season_id"],
            numero_equipe=2,
            force_refresh=True,
        )
        assert res_num.get("status") == "ok", (
            f"Variante 5 (+ numéro) a échoué: {res_num}"
        )
        assert res_num.get("data", {}).get("match_id") == "200000014753792"

        # 6. Ajout de poule uniquement (+ poule_id="200000003057825")
        res_poule = await ffbb_last_result(
            organisme_id=f["org_id"],
            engagement_id=f["eng_u13m2"],
            season_id=f["season_id"],
            poule_id=f["poule_u13m2"],
            force_refresh=True,
        )
        assert res_poule.get("status") == "ok", (
            f"Variante 6 (+ poule) a échoué: {res_poule}"
        )
        assert res_poule.get("data", {}).get("match_id") == "200000014753792"

        # 7. Tous les discriminants cohérents (Reproduction C de l'audit)
        res_c = await ffbb_last_result(
            organisme_id=f["org_id"],
            categorie="U13M2",
            numero_equipe=2,
            engagement_id=f["eng_u13m2"],
            poule_id=f["poule_u13m2"],
            season_id=f["season_id"],
            force_refresh=True,
        )
        assert res_c.get("status") == "ok", (
            f"Variante 7 (Reproduction C) a échoué: {res_c}"
        )
        assert res_c.get("data", {}).get("match_id") == "200000014753792"

        # 8. Discriminants contradictoires (engagement U13M2 avec une poule incompatible)
        res_conflict = await ffbb_last_result(
            organisme_id=f["org_id"],
            engagement_id=f["eng_u13m2"],
            poule_id="99999999999",  # Poule qui ne correspond pas à cet engagement
            force_refresh=True,
        )
        assert res_conflict.get("status") in ("error", "conflict"), (
            f"Variante 8 (discriminants contradictoires) aurait dû signaler une erreur: {res_conflict}"
        )
