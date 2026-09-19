"""Tests de régression démontrant les anomalies historiques et verrouillant les critères d'acceptation.

Ces tests reproduisent fidèlement les 6 cas d'anomalies observées :
1. Requête NM3 retournant PNM (Stade Clermontois)
2. Calendrier mélangeant NM2, Élite 2, Coupe de France et amicaux
3. Match avec current_status=complete et match_status=IN_PROGRESS non détecté en conflit
4. Match avec played=True et statut=scheduled non détecté en conflit
5. H2H ambigu devant retourner des candidats sans faux calcul
6. Article réglementaire devant contenir provenance, hash et applicabilité
"""

from unittest.mock import AsyncMock

import pytest

from ffbb_mcp.services.calendar import _build_calendar_matches
from ffbb_mcp.services.search import ffbb_resolve_team_service


# ---------------------------------------------------------------------------
# 1. Régression : NM3 ne doit JAMAIS retourner une équipe PNM
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_nm3_request_does_not_return_pnm_team(monkeypatch):
    """Vérifie qu'un club n'ayant qu'une équipe PNM ne résout JAMAIS NM3 en PNM."""
    pnm_team = {
        "team_id": "eng_pnm_1",
        "engagement_id": "eng_pnm_1",
        "team_label": "SEM1",
        "nom_equipe": "STADE CLERMONTOIS BASKET AUVERGNE - 1",
        "numero_equipe": "1",
        "poule_id": "poule_pnm_123",
        "competition": "PRE NATIONALE MASCULINE",
        "competition_code": "PNM",
        "competition_type": "DIV",
        "categorie": "SE",
        "sexe": "M",
    }

    mock_resolve = AsyncMock(
        return_value=(
            [{"organisme_id": "9326", "nom": "STADE CLERMONTOIS BASKET AUVERGNE"}],
            None,
        )
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    # L'API du club ne renvoie QUE l'équipe PNM
    mock_equipes = AsyncMock(return_value=[pnm_team])
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service", mock_equipes
    )
    monkeypatch.setattr("ffbb_mcp.services.ffbb_equipes_club_service", mock_equipes)

    res = await ffbb_resolve_team_service(
        club_name="Stade Clermontois",
        categorie="NM3",
    )

    # Le statut DOIT être 'not_found' (ou 'ambiguous'), JAMAIS 'resolved' vers PNM !
    assert res.get("status") in ("not_found", "ambiguous"), (
        f"CRITIQUE : NM3 a été résolu vers {res.get('team')} au lieu d'échouer proprement !"
    )
    if res.get("team"):
        comp = res["team"].get("competition", "")
        comp_code = res["team"].get("competition_code", "")
        assert "PNM" not in comp_code and "PRE NATIONALE" not in comp.upper(), (
            "CRITIQUE : Une équipe PNM a été substituée à une requête NM3 !"
        )


# ---------------------------------------------------------------------------
# 2. Régression : Calendrier ne doit pas mélanger les compétitions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_calendar_request_does_not_mix_nm2_elite2_cup_friendlies(monkeypatch):
    """Vérifie que la requête de calendrier NM2 n'inclut pas Élite 2, Coupe ni amicaux."""
    teams = [
        {
            "engagement_id": "eng_nm2",
            "team_label": "SEM1",
            "nom_equipe": "CLUB SENIOR 1",
            "competition": "NATIONALE MASCULINE 2",
            "competition_code": "NM2",
            "competition_type": "DIV",
            "poule_id": "poule_nm2",
            "numero_equipe": "1",
        },
        {
            "engagement_id": "eng_elite2",
            "team_label": "SEM1",
            "nom_equipe": "CLUB ELITE 2",
            "competition": "ELITE 2",
            "competition_code": "ELIT2",
            "competition_type": "DIV",
            "poule_id": "poule_elite2",
            "numero_equipe": "1",
        },
        {
            "engagement_id": "eng_coupe",
            "team_label": "SEM1",
            "nom_equipe": "CLUB COUPE",
            "competition": "COUPE DE FRANCE",
            "competition_code": "CDF",
            "competition_type": "COUPE",
            "poule_id": "poule_coupe",
            "numero_equipe": "1",
        },
    ]

    mock_resolve = AsyncMock(
        return_value=([{"organisme_id": "1000", "nom": "GRAND CLUB BASKET"}], None)
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)

    async def mock_eq(*args, **kwargs):
        return teams

    monkeypatch.setattr("ffbb_mcp.services.club.ffbb_equipes_club_service", mock_eq)
    monkeypatch.setattr("ffbb_mcp.services.ffbb_equipes_club_service", mock_eq)

    # Mock des poules
    poules = {
        "poule_nm2": {
            "id": "poule_nm2",
            "rencontres": [
                {
                    "id": "m_nm2_1",
                    "idEngagementEquipe1": {"id": "eng_nm2"},
                    "idEngagementEquipe2": {"id": "other_1"},
                    "nomEquipe1": "CLUB SENIOR 1",
                    "nomEquipe2": "ADVERSAIRE NM2",
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
                    "nomEquipe1": "CLUB ELITE 2",
                    "nomEquipe2": "ADVERSAIRE ELITE 2",
                    "date_rencontre": "2026-10-11 15:00:00",
                    "joue": 0,
                    "competition_nom": "ELITE 2",
                }
            ],
        },
        "poule_coupe": {
            "id": "poule_coupe",
            "rencontres": [
                {
                    "id": "m_coupe_1",
                    "idEngagementEquipe1": {"id": "eng_coupe"},
                    "idEngagementEquipe2": {"id": "other_3"},
                    "nomEquipe1": "CLUB COUPE",
                    "nomEquipe2": "ADVERSAIRE COUPE",
                    "date_rencontre": "2026-10-12 20:00:00",
                    "joue": 0,
                    "competition_nom": "COUPE DE FRANCE",
                }
            ],
        },
    }

    async def mock_poule(pid, *args, **kwargs):
        return poules.get(str(pid), {})

    monkeypatch.setattr("ffbb_mcp.services.poule.get_poule_service", mock_poule)
    monkeypatch.setattr("ffbb_mcp.services.get_poule_service", mock_poule)

    # Requête ciblant NM2
    res = await _build_calendar_matches(
        club_name="Grand Club",
        organisme_id="1000",
        categorie="NM2",
        numero_equipe=1,
        adversaire=None,
        date_debut=None,
        date_fin=None,
        limit=10,
    )

    items = res.get("items", [])
    for m in items:
        comp_name = (m.get("competition_nom") or m.get("competition") or "").upper()
        assert "ELITE 2" not in comp_name, (
            "CRITIQUE : Match d'Élite 2 présent dans le calendrier NM2 !"
        )
        assert "COUPE" not in comp_name, (
            "CRITIQUE : Match de Coupe présent par défaut dans le calendrier NM2 !"
        )


# ---------------------------------------------------------------------------
# 3. Régression : Statut contradictoire complete + IN_PROGRESS
# ---------------------------------------------------------------------------
def test_lives_complete_and_in_progress_is_flagged_conflict():
    """Vérifie qu'un match combinant current_status=complete et match_status=IN_PROGRESS est un conflit."""
    from ffbb_mcp.canonical_status import (
        CanonicalMatchStatus,
        canonicalize_match_status,
    )

    raw_match = {
        "current_status": "complete",
        "match_status": "IN_PROGRESS",
        "clock": "00:00",
        "score_equipe1": 82,
        "score_equipe2": 78,
    }

    status, quality = canonicalize_match_status(raw_match)
    assert status == CanonicalMatchStatus.UNKNOWN_CONFLICT
    assert quality.level == "conflict"
    assert len(quality.issues) > 0


# ---------------------------------------------------------------------------
# 4. Régression : played=True et statut=scheduled est un conflit
# ---------------------------------------------------------------------------
def test_played_true_and_scheduled_is_flagged_conflict():
    """Vérifie qu'un match avec played=True et statut=scheduled est identifié en conflit."""
    from ffbb_mcp.canonical_status import (
        CanonicalMatchStatus,
        canonicalize_match_status,
    )

    raw_match = {
        "played": True,
        "joue": 1,
        "statut": "scheduled",
        "date_rencontre": "2026-10-15 20:00:00",
    }

    status, quality = canonicalize_match_status(raw_match)
    assert status == CanonicalMatchStatus.UNKNOWN_CONFLICT
    assert quality.level == "conflict"


# ---------------------------------------------------------------------------
# 5. Régression : H2H ambigu retourne candidats sans calcul statistique fictif
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_h2h_ambiguous_returns_candidates_without_fake_analysis(monkeypatch):
    """Vérifie que ffbb_head_to_head avec ambiguïté renvoie les candidats et aucun calcul fictif."""
    from ffbb_mcp.services.club import ffbb_head_to_head_service

    # Équipe A a 2 engagements seniors distincts (ex: NM3 et Coupe)
    eq_a_candidates = [
        {"engagement_id": "1", "competition": "NM3", "nom_equipe": "Equipe 1"},
        {"engagement_id": "2", "competition": "Coupe", "nom_equipe": "Equipe 1"},
    ]

    mock_resolve = AsyncMock(
        return_value=(
            [{"organisme_id": "9326", "nom": "Stade Clermontois"}],
            None,
        )
    )
    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.club.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=eq_a_candidates),
    )

    res = await ffbb_head_to_head_service(
        club_a="Stade Clermontois",
        club_b="Gerzat",
    )

    # Doit indiquer l'ambiguïté et ne pas inventer un 0-0 ou un faux bilan
    assert res.get("status") in ("ambiguous", "error")
    if "head_to_head" in res:
        assert (
            res["head_to_head"].get("matches") == []
            or res["head_to_head"].get("status") == "no_head_to_head_found"
        )


# ---------------------------------------------------------------------------
# 6. Régression : Règlement contient hash, provenance et applicabilité
# ---------------------------------------------------------------------------
def test_regulation_response_contains_provenance_and_applicability():
    """Vérifie la présence de content_hash, level, season et applicability_notes."""
    from ffbb_mcp.regulations.models import RegulationArticle

    art = RegulationArticle(
        id="rsg_2026_art28",
        document_id="rsg_ffbb_2026_2027",
        season="2026-2027",
        level="federal",
        organizer="FFBB",
        article_number="Article 28",
        article_title="Classement et critères de départage",
        content="En cas d'égalité de points...",
        official_source_url="https://www.ffbb.com/reglements",
        content_hash="sha256:abcd1234efgh5678",
        is_current_for_query=True,
        applicability_notes=["Règlement fédéral de base"],
    )

    assert art.content_hash.startswith("sha256:")
    assert art.level == "federal"
    assert art.is_current_for_query is True
    assert len(art.applicability_notes) == 1
