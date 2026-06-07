from ffbb_mcp.models import BilanResponse, CalendrierMatch


def test_calendrier_match_none_scores():
    data = {
        "id": "123",
        "score_equipe1": "None",
        "score_equipe2": "None",
        "joue": "None",
    }
    match = CalendrierMatch(**data)
    assert match.score_equipe1 is None
    assert match.score_equipe2 is None
    assert match.joue is None


def test_calendrier_match_competition_type_default():
    match = CalendrierMatch(id="1")
    assert match.competition_type == "poule"


def test_calendrier_match_competition_type_elimination():
    match = CalendrierMatch(id="1", competition_type="elimination")
    assert match.competition_type == "elimination"


def test_bilan_response_saison_terminee_default():
    bilan = BilanResponse(
        club="Test Club",
        categorie="U11M",
        bilan_total={
            "match_joues": 5,
            "gagnes": 3,
            "perdus": 2,
            "nuls": 0,
            "paniers_marques": 100,
            "paniers_encaisses": 80,
            "difference": 20,
        },
    )
    assert bilan.saison_terminee is True


def test_bilan_response_saison_terminee_false_when_phase_active():
    bilan = BilanResponse(
        club="Test Club",
        categorie="U11M",
        bilan_total={
            "match_joues": 5,
            "gagnes": 3,
            "perdus": 2,
            "nuls": 0,
            "paniers_marques": 100,
            "paniers_encaisses": 80,
            "difference": 20,
        },
        saison_terminee=False,
    )
    assert bilan.saison_terminee is False
