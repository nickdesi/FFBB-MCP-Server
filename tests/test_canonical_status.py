"""Matrice exhaustive des tests de statut canonique et exclusion des conflits."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ffbb_mcp.canonical_status import (
    CanonicalMatchStatus,
    TemporalMatchStatus,
    canonicalize_match_status,
    derive_temporal_match_status,
    is_match_eligible_for_aggregate,
)


@pytest.mark.parametrize(
    "raw_match, expected_status, is_conflict",
    [
        # 1. played=true + scheduled -> unknown_conflict
        (
            {"played": True, "statut": "scheduled"},
            CanonicalMatchStatus.UNKNOWN_CONFLICT,
            True,
        ),
        # 2. complete + IN_PROGRESS -> unknown_conflict
        (
            {
                "current_status": "complete",
                "match_status": "IN_PROGRESS",
                "score_equipe1": 70,
                "score_equipe2": 65,
            },
            CanonicalMatchStatus.UNKNOWN_CONFLICT,
            True,
        ),
        # 3. true + final + complete + FINAL -> final
        (
            {
                "played": True,
                "joue": 1,
                "statut": "final",
                "current_status": "FINAL",
                "match_status": "FINAL",
                "score_equipe1": 80,
                "score_equipe2": 72,
            },
            CanonicalMatchStatus.FINAL,
            False,
        ),
        # 4. false + scheduled + SCHEDULED -> scheduled
        (
            {
                "played": False,
                "joue": 0,
                "statut": "scheduled",
                "match_status": "SCHEDULED",
            },
            CanonicalMatchStatus.SCHEDULED,
            False,
        ),
        # 5. false + live + IN_PROGRESS -> live
        (
            {
                "played": False,
                "joue": 0,
                "statut": "live",
                "match_status": "IN_PROGRESS",
                "score_equipe1": 42,
                "score_equipe2": 38,
            },
            CanonicalMatchStatus.LIVE,
            False,
        ),
        # 6. Forfait 20-0
        (
            {
                "played": True,
                "statut": "forfait",
                "score_equipe1": 20,
                "score_equipe2": 0,
            },
            CanonicalMatchStatus.FORFEIT_AWAY,
            False,
        ),
        # 7. Annulé
        (
            {
                "played": False,
                "statut": "annulé",
                "match_status": "CANCELLED",
            },
            CanonicalMatchStatus.CANCELLED,
            False,
        ),
        # 8. Reporté
        (
            {
                "played": False,
                "statut": "reporté",
                "match_status": "POSTPONED",
            },
            CanonicalMatchStatus.POSTPONED,
            False,
        ),
    ],
)
def test_canonical_status_matrix(raw_match, expected_status, is_conflict):
    status, quality = canonicalize_match_status(raw_match)
    assert status == expected_status
    if is_conflict:
        assert quality.level == "conflict"
        assert len(quality.issues) > 0
    else:
        assert quality.level == "high"


def test_complete_and_in_progress_is_conflict():
    status, quality = canonicalize_match_status(
        {
            "current_status": "complete",
            "match_status": "IN_PROGRESS",
        }
    )
    assert status == CanonicalMatchStatus.UNKNOWN_CONFLICT
    assert quality.level == "conflict"


def test_played_true_and_scheduled_is_conflict():
    status, quality = canonicalize_match_status(
        {
            "played": True,
            "statut": "scheduled",
        }
    )
    assert status == CanonicalMatchStatus.UNKNOWN_CONFLICT
    assert quality.level == "conflict"


def test_conflicting_match_is_excluded_from_aggregates():
    status, quality = canonicalize_match_status(
        {
            "played": True,
            "statut": "scheduled",
        }
    )
    assert is_match_eligible_for_aggregate(status, quality) is False


def test_cancelled_match_is_excluded_from_aggregates():
    status, quality = canonicalize_match_status({"statut": "annulé"})
    assert is_match_eligible_for_aggregate(status, quality) is False


def test_postponed_match_is_excluded_from_aggregates():
    status, quality = canonicalize_match_status({"statut": "reporté"})
    assert is_match_eligible_for_aggregate(status, quality) is False


def test_final_match_with_valid_score_is_included_in_aggregates():
    status, quality = canonicalize_match_status(
        {
            "played": True,
            "statut": "final",
            "score_equipe1": 85,
            "score_equipe2": 80,
        }
    )
    assert status == CanonicalMatchStatus.FINAL
    assert is_match_eligible_for_aggregate(status, quality) is True


def test_live_match_is_not_returned_as_final():
    status, _ = canonicalize_match_status(
        {
            "played": False,
            "match_status": "IN_PROGRESS",
        }
    )
    assert status in (
        CanonicalMatchStatus.LIVE,
        CanonicalMatchStatus.HALFTIME,
        CanonicalMatchStatus.OVERTIME,
    )
    assert status != CanonicalMatchStatus.FINAL


def test_final_match_is_not_returned_as_live_by_default():
    status, _ = canonicalize_match_status(
        {
            "played": True,
            "match_status": "FINAL",
            "score_equipe1": 90,
            "score_equipe2": 85,
        }
    )
    assert status == CanonicalMatchStatus.FINAL
    assert status not in (
        CanonicalMatchStatus.LIVE,
        CanonicalMatchStatus.HALFTIME,
        CanonicalMatchStatus.OVERTIME,
    )


def test_scheduled_match_after_tipoff_is_presumed_in_progress():
    match = {
        "scheduled_at": "2026-09-20T15:30:00+02:00",
        "statut": "scheduled",
        "played": False,
        "joue": 0,
    }
    canonical_status, _ = canonicalize_match_status(match)

    temporal = derive_temporal_match_status(
        match,
        canonical_status=canonical_status,
        now=datetime(2026, 9, 20, 16, 3, tzinfo=ZoneInfo("Europe/Paris")),
    )

    assert canonical_status == CanonicalMatchStatus.SCHEDULED
    assert temporal.status == TemporalMatchStatus.PRESUMED_IN_PROGRESS
    assert temporal.confidence == "medium"
    assert "33 minute" in temporal.explanation


def test_scheduled_match_long_after_tipoff_has_unknown_status():
    match = {
        "scheduled_at": "2026-09-20T12:00:00+02:00",
        "statut": "scheduled",
        "played": False,
        "joue": 0,
    }

    temporal = derive_temporal_match_status(
        match,
        canonical_status=CanonicalMatchStatus.SCHEDULED,
        now=datetime(2026, 9, 20, 16, 3, tzinfo=ZoneInfo("Europe/Paris")),
    )

    assert temporal.status == TemporalMatchStatus.STATUS_UNKNOWN_AFTER_TIPOFF
    assert temporal.confidence == "low"
