"""Tests des prompts MCP FFBB."""

from ffbb_mcp.prompts import (
    analyser_match,
    bilan_equipe,
    classement_poule,
    expert_basket,
    prochain_match,
    trouver_club,
)


class TestPrompts:
    """Vérifie que les prompts retournent des instructions cohérentes."""

    def test_analyser_match(self):
        result = analyser_match("12345")
        assert "12345" in result
        assert "ffbb_search" in result

    def test_trouver_club_sans_departement(self):
        result = trouver_club("ASVEL")
        assert "ASVEL" in result
        assert "ffbb_search" in result
        assert "ffbb_get" in result

    def test_trouver_club_avec_departement(self):
        result = trouver_club("Basket Club", department="Lyon")
        assert "Lyon" in result
        assert "Basket Club" in result

    def test_prochain_match_sans_categorie(self):
        result = prochain_match("Vichy")
        assert "Vichy" in result
        assert "ffbb_club" in result

    def test_prochain_match_avec_categorie(self):
        result = prochain_match("Vichy", categorie="U11M")
        assert "U11M" in result
        assert "Vichy" in result

    def test_classement_poule(self):
        result = classement_poule("Nationale 1")
        assert "Nationale 1" in result
        assert "ffbb_search" in result
        assert "ffbb_get" in result

    def test_bilan_equipe(self):
        result = bilan_equipe("SCBA", "U11M")
        assert "SCBA" in result
        assert "U11M" in result
        assert "ffbb_search" in result
        assert "ffbb_club" in result
        assert "cumule" in result.lower()

    def test_bilan_equipe_prompt_mentions_ffbb_bilan_prioritaire(self):
        prompt = bilan_equipe("ASVEL", "U13M-1")
        assert "ffbb_bilan" in prompt
        assert "EN PRIORITÉ" in prompt or "prioritaire" in prompt

    def test_bilan_equipe_prompt_mentions_anti_pattern_calendrier(self):
        prompt = bilan_equipe("ASVEL", "U13M-1")
        # Vérifie que le prompt mentionne l'usage de ffbb_club(action='calendrier') uniquement en dernier recours
        assert "ffbb_club(action='calendrier')" in prompt
        assert "DERNIER RECOURS" in prompt or "dernier recours" in prompt

    def test_bilan_equipe_prompt_mentions_donnees_live(self):
        prompt = bilan_equipe("ASVEL", "U13M-1")
        assert "toujours LIVE" in prompt or "données FFBB" in prompt

    def test_expert_basket_prompt_best_practices(self):
        prompt = expert_basket()
        # ffbb_bilan doit être mentionné comme outil prioritaire pour le bilan/classement/résultats
        assert "ffbb_bilan" in prompt
        assert "EN PRIORITÉ" in prompt or "prioritaire" in prompt
        # workflow club → équipes → poule
        assert "ffbb_search(type='organismes'" in prompt
        assert "ffbb_club(action='equipes'" in prompt
        assert "ffbb_get(type='poule'" in prompt
        # anti-pattern calendrier en dernier recours
        assert "ffbb_club(action='calendrier'" in prompt
        assert "dernier recours" in prompt or "DERNIER RECOURS" in prompt
        # rappel sur les données live
        assert "toujours live" in prompt.lower() or "données FFBB" in prompt
