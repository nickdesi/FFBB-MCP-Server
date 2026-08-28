"""Tests unitaires pour le module de calcul de dynamique et forme récente."""

from __future__ import annotations

from ffbb_mcp.dynamique import compute_team_dynamique


def test_dynamique_empty_rencontres():
    """Vérifie le comportement avec une liste vide de rencontres."""
    res = compute_team_dynamique([], eng_ids={"123"}, club_nom="SCBA")
    assert res["forme"] == []
    assert res["forme_str"] == ""
    assert res["victoires_5_derniers"] == 0
    assert res["ratio_victoires_5_derniers"] == 0.0
    assert res["serie_actuelle"]["type"] == "aucune"


def test_dynamique_various_matches_and_streak():
    """Vérifie le calcul complet de la forme, de la série et des moyennes."""
    rencontres = [
        # Match 1 : Victoire Domicile (80 - 70)
        {
            "joue": 1,
            "date_rencontre": "2026-01-10T20:00:00Z",
            "nomEquipe1": "STADE CLERMONTOIS",
            "nomEquipe2": "ASVEL",
            "resultatEquipe1": 80,
            "resultatEquipe2": 70,
            "idEngagementEquipe1": {"id": "100"},
            "idEngagementEquipe2": {"id": "200"},
            "nomSalle": "Maison des Sports",
        },
        # Match 2 : Défaite Extérieur (65 - 75)
        {
            "joue": 1,
            "date_rencontre": "2026-01-17T20:00:00Z",
            "nomEquipe1": "CHORALE ROANNE",
            "nomEquipe2": "STADE CLERMONTOIS",
            "resultatEquipe1": 75,
            "resultatEquipe2": 65,
            "idEngagementEquipe1": {"id": "300"},
            "idEngagementEquipe2": {"id": "100"},
        },
        # Match 3 : Victoire Domicile (90 - 60) -> Ecart +30 (meilleure victoire)
        {
            "joue": 1,
            "date_rencontre": "2026-01-24T20:00:00Z",
            "nomEquipe1": "STADE CLERMONTOIS",
            "nomEquipe2": "VICHY",
            "resultatEquipe1": 90,
            "resultatEquipe2": 60,
            "idEngagementEquipe1": {"id": "100"},
            "idEngagementEquipe2": {"id": "400"},
        },
        # Match 4 : Victoire Extérieur (82 - 78)
        {
            "joue": 1,
            "date_rencontre": "2026-01-31T20:00:00Z",
            "nomEquipe1": "MONTLUCON",
            "nomEquipe2": "STADE CLERMONTOIS",
            "resultatEquipe1": 78,
            "resultatEquipe2": 82,
            "idEngagementEquipe1": {"id": "500"},
            "idEngagementEquipe2": {"id": "100"},
        },
        # Match 5 : Victoire Domicile (85 - 80)
        {
            "joue": 1,
            "date_rencontre": "2026-02-07T20:00:00Z",
            "nomEquipe1": "STADE CLERMONTOIS",
            "nomEquipe2": "ISSOIRE",
            "resultatEquipe1": 85,
            "resultatEquipe2": 80,
            "idEngagementEquipe1": {"id": "100"},
            "idEngagementEquipe2": {"id": "600"},
        },
        # Match 6 (non joué) : doit être ignoré
        {
            "joue": 0,
            "date_rencontre": "2026-02-14T20:00:00Z",
            "nomEquipe1": "STADE CLERMONTOIS",
            "nomEquipe2": "LE PUY",
        },
    ]

    res = compute_team_dynamique(
        rencontres, eng_ids={"100"}, club_nom="Stade Clermontois"
    )

    # 5 matchs joués : V, D, V, V, V
    assert res["forme"] == ["V", "D", "V", "V", "V"]
    assert res["forme_str"] == "V-D-V-V-V"
    assert res["victoires_5_derniers"] == 4
    assert res["defaites_5_derniers"] == 1
    assert res["ratio_victoires_5_derniers"] == 80.0

    # Série globale : 3 victoires consécutives (Matchs 3, 4, 5)
    assert res["serie_actuelle"]["type"] == "victoires"
    assert res["serie_actuelle"]["count"] == 3
    assert "3 victoires consécutives" in res["serie_actuelle"]["label"]

    # Série domicile : 3 victoires à domicile (Matchs 1, 3, 5)
    assert res["serie_domicile"]["type"] == "victoires"
    assert res["serie_domicile"]["count"] == 3
    assert "Invaincu à domicile (3 victoires)" in res["serie_domicile"]["label"]

    # Série extérieur : 1 victoire à l'extérieur (Match 4)
    assert res["serie_exterieur"]["type"] == "victoires"
    assert res["serie_exterieur"]["count"] == 1
    assert res["serie_exterieur"]["label"] == "1 victoire à l'extérieur"

    # Moyennes
    # Points marqués : (80 + 65 + 90 + 82 + 85) / 5 = 402 / 5 = 80.4
    assert res["pts_marques_moyenne_5"] == 80.4
    # Points encaissés : (70 + 75 + 60 + 78 + 80) / 5 = 363 / 5 = 72.6
    assert res["pts_encaisses_moyenne_5"] == 72.6
    assert res["diff_moyenne_5"] == 7.8

    # Meilleure victoire et pire défaite
    assert "+30 pts vs VICHY (90 - 60)" in res["meilleure_victoire"]
    assert "-10 pts vs CHORALE ROANNE (65 - 75)" in res["pire_defaite"]


def test_dynamique_fallback_by_club_name():
    """Vérifie le matching par nom de club quand l'ID d'engagement est absent."""
    rencontres = [
        {
            "joue": "1",
            "date_rencontre": "2026-03-01",
            "nomEquipe1": "US BEAUJOLAIS",
            "nomEquipe2": "GERZAT BASKET",
            "resultatEquipe1": "70",
            "resultatEquipe2": "72",
        }
    ]
    res = compute_team_dynamique(rencontres, club_nom="Gerzat")
    assert res["forme"] == ["V"]
    assert res["victoires_5_derniers"] == 1
    assert res["pts_marques_moyenne_5"] == 72.0
    assert res["pts_encaisses_moyenne_5"] == 70.0


def test_dynamique_defeats_streak_and_draws():
    """Vérifie la gestion des séries de défaites et des nuls."""
    rencontres = [
        {
            "joue": 1,
            "date_rencontre": "2026-01-01",
            "nomEquipe1": "TEAM A",
            "nomEquipe2": "TEAM B",
            "resultatEquipe1": 50,
            "resultatEquipe2": 50,
            "idEngagementEquipe1": {"id": "1"},
        },
        {
            "joue": 1,
            "date_rencontre": "2026-01-08",
            "nomEquipe1": "TEAM A",
            "nomEquipe2": "TEAM C",
            "resultatEquipe1": 60,
            "resultatEquipe2": 70,
            "idEngagementEquipe1": {"id": "1"},
        },
        {
            "joue": 1,
            "date_rencontre": "2026-01-15",
            "nomEquipe1": "TEAM D",
            "nomEquipe2": "TEAM A",
            "resultatEquipe1": 80,
            "resultatEquipe2": 65,
            "idEngagementEquipe2": {"id": "1"},
        },
    ]
    res = compute_team_dynamique(
        rencontres, eng_ids={"1"}, club_nom="TEAM A", ratio_global_victoires=50.0
    )
    assert res["forme"] == ["N", "D", "D"]
    assert res["serie_actuelle"]["type"] == "defaites"
    assert res["serie_actuelle"]["count"] == 2
    assert "2 défaites consécutives" in res["serie_actuelle"]["label"]
    assert res["tendance"] == "En baisse ↘️"


def test_dynamique_more_than_5_matches_keeps_latest_5():
    """Vérifie que la forme ne retient que les 5 derniers matchs."""
    rencontres = []
    for i in range(1, 10):
        rencontres.append(
            {
                "joue": 1,
                "date_rencontre": f"2026-01-{i:02d}",
                "nomEquipe1": "TEAM A",
                "nomEquipe2": f"TEAM {i}",
                "resultatEquipe1": 80 + i,
                "resultatEquipe2": 70,
                "idEngagementEquipe1": {"id": "1"},
            }
        )
    res = compute_team_dynamique(rencontres, eng_ids={"1"}, limit=5)
    assert len(res["forme"]) == 5
    assert res["forme"] == ["V", "V", "V", "V", "V"]
    assert res["forme_str"] == "V-V-V-V-V"
    assert res["victoires_5_derniers"] == 5
    assert res["serie_actuelle"]["count"] == 9
