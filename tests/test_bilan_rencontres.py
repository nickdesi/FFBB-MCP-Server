"""Tests ciblés : _engagement_numero et _compute_bilan_from_rencontres (club.py)."""

from ffbb_mcp.services.club import (
    _compute_bilan_from_rencontres,
    _engagement_numero,
)

# ---------------------------------------------------------------------------
# _engagement_numero
# ---------------------------------------------------------------------------


def test_engagement_numero_from_dict():
    assert _engagement_numero({"numeroEquipe": 2}) == 2


def test_engagement_numero_dict_without_key():
    assert _engagement_numero({"id": 10}) is None


def test_engagement_numero_non_dict_returns_none():
    assert _engagement_numero(42) is None
    assert _engagement_numero(None) is None
    assert _engagement_numero("x") is None


# ---------------------------------------------------------------------------
# _compute_bilan_from_rencontres
# ---------------------------------------------------------------------------


def _rencontre(eng1_id, eng2_id, s1, s2, *, joue=1, nom1="A", nom2="B"):
    return {
        "joue": joue,
        "nomEquipe1": nom1,
        "nomEquipe2": nom2,
        "resultatEquipe1": s1,
        "resultatEquipe2": s2,
        "idEngagementEquipe1": {"id": eng1_id},
        "idEngagementEquipe2": {"id": eng2_id},
    }


def test_bilan_none_when_no_rencontres():
    assert _compute_bilan_from_rencontres({}, {"1"}, "Club") is None
    assert _compute_bilan_from_rencontres({"rencontres": []}, {"1"}, "Club") is None


def test_bilan_match_by_engagement_win_home():
    poule = {"rencontres": [_rencontre("1", "2", 80, 70)]}
    stats = _compute_bilan_from_rencontres(poule, {"1"}, "Club")
    assert stats is not None
    assert stats["match_joues"] == 1
    assert stats["gagnes"] == 1
    assert stats["perdus"] == 0
    assert stats["paniers_marques"] == 80
    assert stats["paniers_encaisses"] == 70


def test_bilan_match_by_engagement_loss_away():
    # Notre équipe est côté 2 (engagement "9")
    poule = {"rencontres": [_rencontre("1", "9", 90, 75)]}
    stats = _compute_bilan_from_rencontres(poule, {"9"}, "Club")
    assert stats is not None
    assert stats["perdus"] == 1
    assert stats["paniers_marques"] == 75
    assert stats["paniers_encaisses"] == 90


def test_bilan_draw_counts_nul():
    poule = {"rencontres": [_rencontre("1", "2", 60, 60)]}
    stats = _compute_bilan_from_rencontres(poule, {"1"}, "Club")
    assert stats is not None
    assert stats["nuls"] == 1


def test_bilan_skips_unplayed_and_missing_scores():
    poule = {
        "rencontres": [
            _rencontre("1", "2", 80, 70, joue=0),
            _rencontre("1", "2", None, 70),
            _rencontre("1", "2", 80, None),
        ]
    }
    assert _compute_bilan_from_rencontres(poule, {"1"}, "Club") is None


def test_bilan_fallback_by_name_when_engagement_unknown():
    poule = {
        "rencontres": [
            _rencontre("7", "8", 100, 90, nom1="Stade Clermontois", nom2="Adversaire")
        ]
    }
    stats = _compute_bilan_from_rencontres(poule, {"1"}, "Stade Clermontois")
    assert stats is not None
    assert stats["gagnes"] == 1
    assert stats["paniers_marques"] == 100


def test_bilan_ignores_non_numeric_scores():
    poule = {"rencontres": [_rencontre("1", "2", "abc", 70)]}
    assert _compute_bilan_from_rencontres(poule, {"1"}, "Club") is None
