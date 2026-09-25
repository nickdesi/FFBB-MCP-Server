"""Tests unitaires pour le contrat de présentation, provenance lisible et masquage des IDs."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from ffbb_mcp.presentation import (
    build_ambiguous_presentation,
    build_match_presentation,
    build_provenance_block,
    evaluate_round_reliability,
    format_french_match_datetime,
    format_source_label,
)
from ffbb_mcp.server import (
    ffbb_club,
    ffbb_last_result,
    ffbb_next_match,
    ffbb_team_summary,
)
from ffbb_mcp.services.club import ffbb_last_result_service, ffbb_next_match_service
from ffbb_mcp.services.search import ffbb_resolve_team_service

_PARIS_TZ = ZoneInfo("Europe/Paris")


class TestPresentationHelpers:
    """Tests des fonctions utilitaires du module presentation.py."""

    def test_evaluate_round_reliability_valid(self):
        r1 = evaluate_round_reliability(1)
        assert r1.is_reliable is True
        assert r1.display_value == 1
        assert r1.warning is None

        r14 = evaluate_round_reliability("14")
        assert r14.is_reliable is True
        assert r14.display_value == 14

    def test_evaluate_round_reliability_invalid_or_anomalous(self):
        # Nul ou vide
        r_none = evaluate_round_reliability(None)
        assert r_none.is_reliable is False
        assert r_none.display_value is None

        r_zero = evaluate_round_reliability(0)
        assert r_zero.is_reliable is False
        assert r_zero.display_value is None

        # Aberrant (> 38)
        r_huge = evaluate_round_reliability(48)
        assert r_huge.is_reliable is False
        assert r_huge.display_value is None
        assert "aberrante" in (r_huge.warning or "")

        # Séquence erratique (9, 17, 35, 48)
        r_seq = evaluate_round_reliability(35, context_rounds=[9, 17, 35, 48])
        assert r_seq.is_reliable is False
        assert r_seq.display_value is None
        assert "non séquentielle" in (r_seq.warning or "")

    def test_format_source_label_french(self):
        dt = datetime(2026, 9, 20, 13, 18, tzinfo=_PARIS_TZ)
        label = format_source_label(dt)
        assert label == "Données FFBB consultées le 20 septembre 2026 à 13:18."

    def test_format_french_match_datetime(self):
        dt = datetime(2026, 9, 19, 20, 0, tzinfo=_PARIS_TZ)
        date_iso, time_iso, human_text = format_french_match_datetime(
            dt, time_confirmed=True
        )
        assert date_iso == "2026-09-19"
        assert time_iso == "20:00"
        assert human_text == "samedi 19 septembre à 20 h"

        dt2 = datetime(2026, 9, 19, 20, 30, tzinfo=_PARIS_TZ)
        _, _, human_text2 = format_french_match_datetime(dt2, time_confirmed=True)
        assert human_text2 == "samedi 19 septembre à 20 h 30"

        # Horaire non confirmé
        _, time_unconfirmed, human_text_unconfirmed = format_french_match_datetime(
            dt, time_confirmed=False
        )
        assert time_unconfirmed is None
        assert "horaire à fixer" in human_text_unconfirmed

    def test_build_match_presentation_win_loss_draw(self):
        dt = datetime(2026, 9, 19, 20, 0, tzinfo=_PARIS_TZ)
        r_info = evaluate_round_reliability(1)

        # Victoire à domicile
        p_win = build_match_presentation(
            team_name="GERZAT BASKET",
            opponent_name="US CELLES SUR DUROLLE",
            is_home=True,
            status="final",
            dt_obj=dt,
            time_confirmed=True,
            home_score=36,
            away_score=32,
            venue_name="GYMNASE GEORGES FUSTIER",
            venue_city="GERZAT",
            competition_name="Départementale masculine seniors - Division 3",
            round_info=r_info,
            is_last_result=True,
        )
        assert p_win.short_answer in (
            "Gerzat Basket a battu l'US Celles-sur-Durolle 36 à 32.",
            "Gerzat Basket a battu US Celles sur Durolle 36 à 32.",
        )
        assert "Victoire à domicile samedi 19 septembre à 20 h" in p_win.detail_line
        assert any(
            x in p_win.detail_line.lower()
            for x in ("gymnase georges fustier", "georges fustier")
        )
        assert "1re journée" in p_win.detail_line

        # Défaite à l'extérieur
        p_loss = build_match_presentation(
            team_name="GERZAT BASKET",
            opponent_name="US CELLES SUR DUROLLE",
            is_home=False,
            status="final",
            dt_obj=dt,
            time_confirmed=True,
            home_score=50,
            away_score=40,
            venue_name="Salle Polyvalente",
            venue_city="Celles",
            round_info=r_info,
            is_last_result=True,
        )
        assert "s'est incliné" in p_loss.short_answer
        assert "Défaite à l'extérieur" in p_loss.detail_line

        # Match nul
        p_draw = build_match_presentation(
            team_name="GERZAT BASKET",
            opponent_name="US CELLES SUR DUROLLE",
            is_home=True,
            status="final",
            dt_obj=dt,
            time_confirmed=True,
            home_score=30,
            away_score=30,
            round_info=r_info,
            is_last_result=True,
        )
        assert "Match nul" in p_draw.short_answer
        assert "30 à 30" in p_draw.short_answer

        # Prochain match (domicile et extérieur)
        p_next_home = build_match_presentation(
            team_name="GERZAT BASKET",
            opponent_name="ASM BASKET",
            is_home=True,
            status="scheduled",
            dt_obj=dt,
            time_confirmed=True,
            round_info=r_info,
            is_last_result=False,
        )
        assert "recevra" in p_next_home.short_answer
        assert "Match à domicile programmé" in p_next_home.detail_line

        p_next_away = build_match_presentation(
            team_name="GERZAT BASKET",
            opponent_name="ASM BASKET",
            is_home=False,
            status="scheduled",
            dt_obj=dt,
            time_confirmed=True,
            round_info=r_info,
            is_last_result=False,
        )
        assert "se déplacera chez" in p_next_away.short_answer
        assert "Match à l'extérieur programmé" in p_next_away.detail_line

    def test_build_provenance_block_structure_and_masking(self):
        prov = build_provenance_block(
            source="ffbb_api_live",
            cache_status="miss",
            resource_ids={"competition_id": "501", "poule_id": "901"},
            raw_journee=48,
        )
        assert prov["provider"] == "FFBB"
        assert prov["display_to_user"] is False
        assert prov["data_freshness"] == "live"
        assert prov["technical"]["connector_source_id"] == "ffbb_mcp"
        assert prov["technical"]["cache_status"] == "miss"
        assert prov["technical"]["resource_ids"] == {
            "competition_id": "501",
            "poule_id": "901",
        }
        assert prov["technical"]["raw_journee"] == 48

    def test_build_ambiguous_presentation_no_id_leak(self):
        candidates = [
            {
                "engagement_id": "200000005346869",
                "team_label": "U13F",
                "numero_equipe": None,
                "competition": "RFU13 Brassage",
                "poule_id": "200000003057825",
            },
            {
                "engagement_id": "200000005358422",
                "team_label": "U13F",
                "numero_equipe": 2,
                "competition": "Départementale féminine U13",
                "poule_id": "200000003057826",
            },
        ]
        res = build_ambiguous_presentation(candidates, club_name="Cournon")
        assert res["status"] == "ambiguous"
        prompt = res["clarification_prompt"]
        detail = res["presentation"]["detail_line"]

        # Zéro fuite d'IDs dans les textes de présentation ou de prompt
        assert "200000005346869" not in prompt
        assert "200000005358422" not in prompt
        assert "200000005346869" not in detail
        assert "200000005358422" not in detail

        # Présence des libellés conviviaux
        assert "U13F — RFU13 Brassage" in detail
        assert "U13F 2 — Départementale féminine U13" in detail

        # IDs techniques isolés dans le bloc technique de provenance
        tech_cands = res["provenance"]["technical"]["candidate_ids"]
        assert len(tech_cands) == 2
        assert tech_cands[0]["engagement_id"] == "200000005346869"
        assert tech_cands[1]["engagement_id"] == "200000005358422"


class TestMatchServicesPresentationAndReliability:
    """Tests fonctionnels de ffbb_last_result_service et ffbb_next_match_service."""

    @pytest.mark.asyncio
    async def test_last_result_service_presentation_and_provenance(self, monkeypatch):
        fake_team = {
            "poule_id": "901",
            "engagement_id": "101",
            "competition_id": "501",
            "competition": "Départementale masculine seniors - Division 3",
            "team_label": "Seniors masculins",
            "numero_equipe": 1,
        }
        fake_match = {
            "id": "match_999",
            "nomEquipe1": "GERZAT BASKET",
            "nomEquipe2": "US CELLES SUR DUROLLE",
            "resultatEquipe1": 36,
            "resultatEquipe2": 32,
            "date_rencontre": "2026-09-19 20:00:00",
            "numeroJournee": 1,
            "joue": 1,
            "nomSalle": "GYMNASE GEORGES FUSTIER",
            "villeSalle": "GERZAT",
            "idEngagementEquipe1": "101",
            "idEngagementEquipe2": "102",
        }

        mock_resolve = AsyncMock(
            return_value=(
                None,
                [fake_team],
                {"organisme_id": "9326", "nom": "GERZAT BASKET"},
            )
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.club._resolve_team_equipes", mock_resolve
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.club._fetch_poule_matches",
            AsyncMock(return_value=[(fake_match, fake_team)]),
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.search.get_rencontre_service",
            AsyncMock(return_value=fake_match),
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.salle._enrich_with_salle_details",
            AsyncMock(return_value=fake_match),
        )

        res = await ffbb_last_result_service(
            organisme_id="9326",
            categorie="SEM",
            numero_equipe=1,
        )

        assert res["status"] == "ok"

        # 1. Vérification du bloc data
        assert "data" in res
        data = res["data"]
        assert data["team"]["name"] == "GERZAT BASKET"
        assert data["match"]["context_label"] == "Dernier match joué"
        assert data["match"]["status"] == "final"
        assert data["match"]["home_score"] == 36
        assert data["match"]["away_score"] == 32
        assert data["match"]["result_for_team"] == "win"
        assert data["match"]["date"] == "2026-09-19"
        assert data["match"]["time"] == "20:00"
        assert data["match"]["timezone"] == "Europe/Paris"
        assert data["match"]["round"]["display_value"] == 1
        assert data["match"]["round"]["is_reliable"] is True

        # 2. Vérification du bloc presentation
        assert "presentation" in res
        pres = res["presentation"]
        assert "Gerzat Basket a battu" in pres["short_answer"]
        assert "36 à 32" in pres["short_answer"]
        assert "Victoire à domicile" in pres["detail_line"]
        assert "samedi 19 septembre à 20 h" in pres["detail_line"]
        assert "Données FFBB consultées le" in pres["source_label"]
        assert pres["warnings"] == []

        # 3. Vérification du bloc provenance
        assert "provenance" in res
        prov = res["provenance"]
        assert prov["provider"] == "FFBB"
        assert prov["display_to_user"] is False
        assert prov["technical"]["connector_source_id"] == "ffbb_mcp"
        assert prov["technical"]["resource_ids"]["match_id"] == "match_999"

        # 4. Rétrocompatibilité : champs au 1er niveau
        assert res["score_domicile"] == 36
        assert res["score_exterieur"] == 32
        assert res["domicile"] == "GERZAT BASKET"
        assert res["victoire"] is True
        assert res["journee"] == 1

        # 5. Zéro pseudo-citation technique
        for val in [pres["short_answer"], pres["detail_line"], pres["source_label"]]:
            assert "[ffbb_mcp_" not in val
            assert "connector_source_id" not in val

    @pytest.mark.asyncio
    async def test_last_result_unreliable_round_sets_null_and_warns(self, monkeypatch):
        """Si la journée est aberrante (ex: 48), journee doit être null et un warning généré."""
        fake_team = {
            "poule_id": "901",
            "engagement_id": "101",
            "competition_id": "501",
            "competition": "Départementale",
            "team_label": "Seniors",
            "numero_equipe": 1,
        }
        fake_match = {
            "id": "match_999",
            "nomEquipe1": "GERZAT BASKET",
            "nomEquipe2": "US CELLES SUR DUROLLE",
            "resultatEquipe1": 36,
            "resultatEquipe2": 32,
            "date_rencontre": "2026-09-19 20:00:00",
            "numeroJournee": 48,  # Aberrant
            "joue": 1,
            "idEngagementEquipe1": "101",
            "idEngagementEquipe2": "102",
        }

        mock_resolve = AsyncMock(
            return_value=(
                None,
                [fake_team],
                {"organisme_id": "9326", "nom": "GERZAT BASKET"},
            )
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.club._resolve_team_equipes", mock_resolve
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.club._fetch_poule_matches",
            AsyncMock(return_value=[(fake_match, fake_team)]),
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.search.get_rencontre_service",
            AsyncMock(return_value=fake_match),
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.salle._enrich_with_salle_details",
            AsyncMock(return_value=fake_match),
        )

        res = await ffbb_last_result_service(
            organisme_id="9326",
            categorie="SEM",
            numero_equipe=1,
        )

        # Journée null et non fiable
        assert res["journee"] is None
        assert res["data"]["match"]["round"]["display_value"] is None
        assert res["data"]["match"]["round"]["is_reliable"] is False
        assert len(res["presentation"]["warnings"]) >= 1
        assert "aberrante" in res["presentation"]["warnings"][0]
        # Valeur brute préservée dans les métadonnées techniques
        assert res["provenance"]["technical"]["raw_journee"] == 48

    @pytest.mark.asyncio
    async def test_next_match_service_presentation_and_provenance(self, monkeypatch):
        fake_team = {
            "poule_id": "901",
            "engagement_id": "101",
            "competition_id": "501",
            "competition": "Régionale 2",
            "team_label": "Senior M1",
            "numero_equipe": 1,
        }
        fake_match = {
            "id": "next_101",
            "nomEquipe1": "GERZAT BASKET",
            "nomEquipe2": "ASM BASKET",
            "date_rencontre": "2026-10-04 15:30:00",
            "numeroJournee": 2,
            "joue": 0,
            "idEngagementEquipe1": "101",
            "idEngagementEquipe2": "105",
            "nomSalle": "Gymnase Georges Fustier",
            "villeSalle": "Gerzat",
        }

        mock_resolve = AsyncMock(
            return_value=(
                None,
                [fake_team],
                {"organisme_id": "9326", "nom": "GERZAT BASKET"},
            )
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.club._resolve_team_equipes", mock_resolve
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.club._fetch_poule_matches",
            AsyncMock(return_value=[(fake_match, fake_team)]),
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.search.get_rencontre_service",
            AsyncMock(return_value=fake_match),
        )
        monkeypatch.setattr(
            "ffbb_mcp.services.salle._enrich_with_salle_details",
            AsyncMock(return_value=fake_match),
        )

        res = await ffbb_next_match_service(
            organisme_id="9326",
            categorie="SEM",
            numero_equipe=1,
        )

        assert res["status"] == "ok"
        assert res["data"]["match"]["context_label"] == "Prochain match programmé"
        assert res["data"]["match"]["status"] == "scheduled"
        assert res["data"]["match"]["date"] == "2026-10-04"
        assert res["data"]["match"]["time"] == "15:30"
        assert "recevra" in res["presentation"]["short_answer"]
        assert "dimanche 4 octobre à 15 h 30" in res["presentation"]["detail_line"]
        assert res["provenance"]["display_to_user"] is False
        assert res["match"]["match_id"] == "next_101"


class TestResolveTeamServicePresentation:
    """Tests de la présentation et masquage d'IDs dans ffbb_resolve_team_service."""

    @pytest.mark.asyncio
    async def test_resolve_team_service_ambiguous_presentation(self):
        cands = [
            {
                "engagement_id": "200000005346869",
                "team_label": "U13F",
                "numero_equipe": None,
                "competition": "RFU13 Brassage",
                "poule_id": "200000003057825",
            },
            {
                "engagement_id": "200000005358422",
                "team_label": "U13F",
                "numero_equipe": 2,
                "competition": "Départementale féminine U13",
                "poule_id": "200000003057826",
            },
        ]
        with patch(
            "ffbb_mcp.strict_resolver.resolve_team_strict",
            AsyncMock(
                return_value=MagicMock(
                    status="ambiguous",
                    selected=None,
                    candidates=cands,
                    club_resolu={"nom": "Cournon"},
                    ambiguity_message="Plusieurs équipes existent",
                    clarification_prompt="Précisez la division",
                    model_dump=lambda: {"candidates": cands},
                )
            ),
        ):
            res = await ffbb_resolve_team_service(club_name="Cournon", categorie="U13F")
            assert res["status"] == "ambiguous"
            assert "presentation" in res
            assert "provenance" in res
            assert "200000005346869" not in res["clarification_prompt"]
            assert "200000005346869" not in res["presentation"]["detail_line"]


class TestServerToolsPresentation:
    """Tests des outils au niveau du serveur MCP (ffbb_team_summary, ffbb_club, etc.)."""

    @pytest.mark.asyncio
    async def test_team_summary_has_presentation_and_provenance(self):
        mock_resolve = AsyncMock(
            return_value={
                "status": "resolved",
                "team": {"team_label": "SEM1", "engagement_id": "101"},
            }
        )
        mock_bilan = AsyncMock(
            return_value={
                "status": "ok",
                "phase_courante": {"competition": "PNM"},
                "bilan_total": {"victoires": 10, "defaites": 2},
            }
        )
        mock_last = AsyncMock(
            return_value={
                "status": "ok",
                "score_domicile": 80,
                "score_exterieur": 70,
                "presentation": {"short_answer": "Victoire 80 à 70."},
            }
        )
        mock_next = AsyncMock(
            return_value={
                "status": "ok",
                "presentation": {"short_answer": "Prochain match samedi."},
            }
        )

        with (
            patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
            patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
            patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
            patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        ):
            res = await ffbb_team_summary(
                organisme_id=9326,
                categorie="SEM",
                numero_equipe=1,
            )
            assert res["status"] == "ok"
            assert "team" in res
            assert "presentation" in res
            assert "provenance" in res
            assert "10 victoires, 2 défaites" in res["presentation"]["short_answer"]
            assert res["provenance"]["display_to_user"] is False

    @pytest.mark.asyncio
    async def test_team_summary_propagates_ambiguity(self):
        ambig_res = {
            "status": "ambiguous",
            "team": None,
            "candidates": [{"team_label": "U13F 1"}, {"team_label": "U13F 2"}],
            "clarification_prompt": "Précisez votre choix.",
            "presentation": {"short_answer": "Plusieurs équipes trouvées."},
            "provenance": {"provider": "FFBB"},
        }
        with patch(
            "ffbb_mcp.server.ffbb_resolve_team_service",
            AsyncMock(return_value=ambig_res),
        ):
            res = await ffbb_team_summary(
                club_name="Cournon",
                categorie="U13F",
            )
            assert res["status"] == "ambiguous"
            assert res["presentation"]["short_answer"] == "Plusieurs équipes trouvées."

    @pytest.mark.asyncio
    async def test_ffbb_club_calendrier_presentation(self):
        fake_matches = [
            {
                "id": "1",
                "date": "2026-09-20",
                "equipe1": "SCBA",
                "equipe2": "ASM",
                "journee": 1,
            }
        ]
        with patch(
            "ffbb_mcp.server.get_calendrier_club_service",
            AsyncMock(
                return_value={
                    "items": fake_matches,
                    "presentation": {
                        "short_answer": "1 rencontre(s) au calendrier.",
                        "detail_line": "1 rencontre(s) affichée(s).",
                        "source_label": "Données FFBB",
                        "warnings": [],
                    },
                    "provenance": {"provider": "FFBB", "display_to_user": False},
                    "_meta": {"total": 1},
                }
            ),
        ):
            res = await ffbb_club(
                action="calendrier",
                club_name="SCBA",
                categorie="SEM",
            )
            assert isinstance(res, dict)
            assert "presentation" in res
            assert "provenance" in res
            assert (
                res["presentation"]["short_answer"] == "1 rencontre(s) au calendrier."
            )

    @pytest.mark.asyncio
    async def test_ffbb_last_result_and_next_match_tools(self):
        mock_last = AsyncMock(
            return_value={
                "status": "ok",
                "presentation": {"short_answer": "Victoire"},
                "provenance": {"provider": "FFBB"},
            }
        )
        mock_next = AsyncMock(
            return_value={
                "status": "ok",
                "presentation": {"short_answer": "Prochain match"},
                "provenance": {"provider": "FFBB"},
            }
        )
        with (
            patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
            patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
        ):
            lr = await ffbb_last_result(organisme_id=9326, categorie="SEM1")
            assert lr["status"] == "ok"
            assert lr["presentation"]["short_answer"] == "Victoire"

            nm = await ffbb_next_match(organisme_id=9326, categorie="SEM1")
            assert nm["status"] == "ok"
            assert nm["presentation"]["short_answer"] == "Prochain match"
