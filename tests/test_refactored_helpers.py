"""Tests for refactored shared helpers: _resolve_team_equipes, _fetch_poule_matches, format_poule_response."""

from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp._state import reset_service_state
from ffbb_mcp.services import (
    _fetch_poule_matches,
    _prioritize_phase,
    _resolve_team_equipes,
    format_poule_response,
)


@pytest.fixture(autouse=True)
def clear_caches():
    reset_service_state()
    yield


# ---------------------------------------------------------------------------
# _resolve_team_equipes
# ---------------------------------------------------------------------------


class TestResolveTeamEquipes:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_identifiers(self):
        error, equipes, club = await _resolve_team_equipes(
            club_name=None,
            organisme_id=None,
            categorie="U11M",
            numero_equipe=1,
        )
        assert error is not None
        assert error["status"] == "error"
        assert equipes == []
        assert club is None

    @pytest.mark.asyncio
    async def test_returns_not_found_when_club_unknown(self):
        with patch(
            "ffbb_mcp.services._resolve_club_and_org",
            new_callable=AsyncMock,
            return_value=([], None),
        ):
            error, equipes, club = await _resolve_team_equipes(
                club_name="Inexistant",
                organisme_id=None,
                categorie="U11M",
                numero_equipe=None,
            )
        assert error["status"] == "not_found"
        assert "introuvable" in error["message"]

    @pytest.mark.asyncio
    async def test_returns_ambiguous_when_multiple_clubs(self):
        clubs = [
            {"organisme_id": 1, "nom": "Club A"},
            {"organisme_id": 2, "nom": "Club B"},
        ]
        with patch(
            "ffbb_mcp.services._resolve_club_and_org",
            new_callable=AsyncMock,
            return_value=(clubs, None),
        ):
            error, equipes, club = await _resolve_team_equipes(
                club_name="Club",
                organisme_id=None,
                categorie="U11M",
                numero_equipe=None,
            )
        assert error["status"] == "ambiguous"
        assert error["candidates"] == clubs

    @pytest.mark.asyncio
    async def test_filters_by_numero_equipe(self):
        club = {"organisme_id": 9326, "nom": "CSB"}
        equipes = [
            {"numero_equipe": "1", "team_label": "U11M", "poule_id": 100},
            {"numero_equipe": "2", "team_label": "U11M", "poule_id": 200},
        ]
        with (
            patch(
                "ffbb_mcp.services._resolve_club_and_org",
                new_callable=AsyncMock,
                return_value=([club], None),
            ),
            patch(
                "ffbb_mcp.services.ffbb_equipes_club_service",
                new_callable=AsyncMock,
                return_value=equipes,
            ),
        ):
            error, filtered, resolved = await _resolve_team_equipes(
                club_name="CSB",
                organisme_id=None,
                categorie="U11M",
                numero_equipe=2,
            )
        assert error is None
        assert len(filtered) == 1
        assert filtered[0]["numero_equipe"] == "2"
        assert resolved == club

    @pytest.mark.asyncio
    async def test_custom_not_found_status(self):
        with patch(
            "ffbb_mcp.services._resolve_club_and_org",
            new_callable=AsyncMock,
            return_value=([], None),
        ):
            error, _, _ = await _resolve_team_equipes(
                club_name="X",
                organisme_id=None,
                categorie="U11M",
                numero_equipe=None,
                not_found_status="no_result",
            )
        assert error["status"] == "no_result"


# ---------------------------------------------------------------------------
# _fetch_poule_matches
# ---------------------------------------------------------------------------


class TestFetchPouleMatches:
    @pytest.mark.asyncio
    async def test_returns_matches_for_team(self):
        equipes = [
            {"poule_id": 100, "engagement_id": 55, "phase_label": "Phase 1"},
        ]
        poule_data = {
            "rencontres": [
                {
                    "idEngagementEquipe1": {"id": 55, "numeroEquipe": 1},
                    "idEngagementEquipe2": {"id": 66, "numeroEquipe": 1},
                    "nomEquipe1": "CSB",
                    "nomEquipe2": "Adversaire",
                    "joue": 1,
                    "resultatEquipe1": 42,
                    "resultatEquipe2": 30,
                },
                {
                    "idEngagementEquipe1": {"id": 77, "numeroEquipe": 1},
                    "idEngagementEquipe2": {"id": 88, "numeroEquipe": 1},
                    "nomEquipe1": "Autre1",
                    "nomEquipe2": "Autre2",
                    "joue": 1,
                    "resultatEquipe1": 50,
                    "resultatEquipe2": 40,
                },
            ]
        }
        with patch(
            "ffbb_mcp.services.get_poule_service",
            new_callable=AsyncMock,
            return_value=poule_data,
        ):
            matches = await _fetch_poule_matches(
                equipes,
                organisme_nom="CSB",
                numero_equipe=1,
            )
        # Only the match with engagement_id 55 should match
        assert len(matches) == 1
        assert matches[0][0]["nomEquipe1"] == "CSB"

    @pytest.mark.asyncio
    async def test_skips_equipes_without_poule_id(self):
        equipes = [{"engagement_id": 55, "phase_label": "Phase 1"}]  # no poule_id
        matches = await _fetch_poule_matches(
            equipes,
            organisme_nom="CSB",
            numero_equipe=1,
        )
        assert matches == []


# ---------------------------------------------------------------------------
# _prioritize_phase
# ---------------------------------------------------------------------------


class TestPrioritizePhase:
    def test_returns_highest_phase(self):
        matches = [
            ({"id": 1}, {"phase_label": "Phase 1"}),
            ({"id": 2}, {"phase_label": "Phase 2"}),
            ({"id": 3}, {"phase_label": "Phase 2"}),
        ]
        result = _prioritize_phase(matches)
        assert len(result) == 2
        assert all(eq["phase_label"] == "Phase 2" for _, eq in result)

    def test_empty_input(self):
        assert _prioritize_phase([]) == []

    def test_no_phase_label_defaults_to_1(self):
        matches = [
            ({"id": 1}, {"phase_label": None}),
            ({"id": 2}, {"phase_label": "Phase 1"}),
        ]
        result = _prioritize_phase(matches)
        assert len(result) == 2  # both are phase 1


# ---------------------------------------------------------------------------
# format_poule_response
# ---------------------------------------------------------------------------


class TestFormatPouleResponse:
    def test_formats_classements_and_rencontres(self):
        poule_data = {
            "id": 42,
            "libelle": "Poule A",
            "classements": [
                {
                    "id_engagement": {
                        "nom": "CSB REVARD",
                        "numero_equipe": 1,
                        "logo": {"id": "abc123"},
                    },
                    "position": 1,
                }
            ],
            "rencontres": [
                {
                    "idEngagementEquipe1": {"numeroEquipe": 1},
                    "idEngagementEquipe2": {"numeroEquipe": 2},
                    "nomEquipe1": "CLUB A",
                    "nomEquipe2": "CLUB B",
                }
            ],
        }
        result = format_poule_response(poule_data)
        assert result["id"] == 42
        assert result["nom"] == "Poule A"
        assert result["classements"][0]["equipe"] == "CSB REVARD"
        assert "api.ffbb.com/assets/abc123" in result["classements"][0]["logo_url"]
        assert result["rencontres"][0]["nomEquipe1"] == "CLUB A"

    def test_truncation(self, monkeypatch):
        monkeypatch.setenv("FFBB_MAX_CALENDAR_MATCHES", "2")
        poule_data = {
            "id": 1,
            "libelle": "Poule",
            "classements": [],
            "rencontres": [
                {
                    "idEngagementEquipe1": {},
                    "idEngagementEquipe2": {},
                    "nomEquipe1": f"A{i}",
                    "nomEquipe2": f"B{i}",
                }
                for i in range(5)
            ],
        }
        result = format_poule_response(poule_data)
        assert result["_truncated"] is True
        assert result["_total"] == 5
        assert result["_omitted_count"] == 3
        # 2 matches + 1 warning
        assert len(result["rencontres"]) == 3
        assert "warning" in result["rencontres"][-1]

    def test_truncation_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("FFBB_MAX_CALENDAR_MATCHES", "abc")
        poule_data = {
            "id": 1,
            "libelle": "Poule",
            "classements": [],
            "rencontres": [
                {
                    "idEngagementEquipe1": {},
                    "idEngagementEquipe2": {},
                    "nomEquipe1": "A",
                    "nomEquipe2": "B",
                }
            ],
        }
        result = format_poule_response(poule_data)
        assert result["rencontres"][0]["nomEquipe1"] == "A"

    def test_no_logo(self):
        poule_data = {
            "id": 1,
            "libelle": "P",
            "classements": [
                {"id_engagement": {"nom": "X", "numero_equipe": None, "logo": None}}
            ],
            "rencontres": [],
        }
        result = format_poule_response(poule_data)
        assert result["classements"][0]["logo_url"] is None

    def test_format_poule_response_adds_freshness_meta(self):
        result = format_poule_response(
            {"id": "p1", "libelle": "Poule A", "_ttl_seconds": 120}
        )

        meta = result["_meta"]
        assert meta["source"] == "ffbb_api_live"
        assert meta["timezone"] == "Europe/Paris"
        assert meta["cache"] == "poule"
        assert meta["ttl_seconds"] == 120
        assert meta["force_refresh_supported"] is True
        assert "generated_at" in meta


# ---------------------------------------------------------------------------
# _get_inflight_lock thread safety
# ---------------------------------------------------------------------------


class TestInflightLockThreadSafe:
    def test_lock_created_once(self):
        """Verify the lock is created lazily and reused."""
        import ffbb_mcp.services as svc

        # Reset to None
        svc._inflight_lock = None
        lock1 = svc._get_inflight_lock()
        lock2 = svc._get_inflight_lock()
        assert lock1 is lock2
        import asyncio

        assert isinstance(lock1, asyncio.Lock)
