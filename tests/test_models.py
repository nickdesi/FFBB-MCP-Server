from ffbb_mcp.models import CalendrierMatch


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
