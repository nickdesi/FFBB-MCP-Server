"""Tests des prompts MCP FFBB."""

from ffbb_mcp.server import (
    analyser_match,
    bilan_equipe,
    classement_poule,
    prochain_match,
    trouver_club,
)


class TestPrompts:
    """Vérifie que les prompts retournent des instructions cohérentes."""

    def test_analyser_match(self):
        result = analyser_match("12345")
        assert "12345" in result
        assert "ffbb_search_rencontres" in result

    def test_trouver_club_sans_departement(self):
        result = trouver_club("ASVEL")
        assert "ASVEL" in result
        assert "ffbb_search_organismes" in result
        assert "ffbb_get_organisme" in result

    def test_trouver_club_avec_departement(self):
        result = trouver_club("Basket Club", department="Lyon")
        assert "Lyon" in result
        assert "Basket Club" in result

    def test_prochain_match_sans_categorie(self):
        result = prochain_match("Vichy")
        assert "Vichy" in result
        assert "ffbb_calendrier_club" in result

    def test_prochain_match_avec_categorie(self):
        result = prochain_match("Vichy", categorie="U11M")
        assert "U11M" in result
        assert "Vichy" in result

    def test_classement_poule(self):
        result = classement_poule("Nationale 1")
        assert "Nationale 1" in result
        assert "ffbb_search_competitions" in result
        assert "ffbb_get_classement" in result

    def test_bilan_equipe(self):
        result = bilan_equipe("SCBA", "U11M")
        assert "SCBA" in result
        assert "U11M" in result
        assert "ffbb_equipes_club" in result
        assert "ffbb_get_classement" in result
        assert "cumule" in result.lower()
