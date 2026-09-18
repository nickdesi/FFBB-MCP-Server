"""Tests des prompts MCP FFBB."""

from ffbb_mcp.prompts import (
    ROUTING_PROMPT,
    analyser_match,
    bilan_equipe,
    calendrier_equipe,
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
        assert "ffbb_next_match" in result
        assert "SINGULIER" in result
        assert "ffbb_club(action='calendrier')" in result

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
        assert "global" in result.lower()

    def test_bilan_equipe_prompt_mentions_ffbb_bilan_prioritaire(self):
        prompt = bilan_equipe("ASVEL", "U13M-1")
        assert "ffbb_bilan" in prompt
        assert "détail par phase" in prompt

    def test_bilan_equipe_prompt_mentions_anti_pattern_calendrier(self):
        prompt = bilan_equipe("ASVEL", "U13M-1")
        assert "ffbb_club(action='calendrier'" in prompt
        assert "tier 3" in prompt.lower()

    def test_expert_basket_prompt_best_practices(self):
        prompt = expert_basket()
        # ffbb_bilan doit être mentionné comme super-outil
        assert "ffbb_bilan" in prompt
        # Le workflow Tier 1 doit mentionner les super-outils en premier
        assert (
            "Tier 1" in prompt
            or "super-outil" in prompt.lower()
            or "en premier" in prompt.lower()
        )
        # workflow club → équipes → poule toujours présent en Tier 2/3
        assert "ffbb_search(type='organismes'" in prompt or "ffbb_search" in prompt
        assert "ffbb_club(action='equipes'" in prompt
        assert "ffbb_get(type='poule'" in prompt
        # pipeline manuel en dernier recours
        assert "ffbb_club(action='calendrier'" in prompt
        assert "dernier recours" in prompt.lower()
        # rappel sur les données live
        assert "toujours live" in prompt.lower() or "données FFBB" in prompt

        # --- NOUVELLES RÈGLES D'AFFICHAGE ---
        assert "AFFICHAGE DES MATCHS" in prompt
        assert "equipe1" in prompt and "equipe2" in prompt
        assert "Format tableau obligatoire" in prompt
        assert "🟢" in prompt
        assert "score" in prompt.lower()
        assert "domicile" in prompt.lower() and "extérieur" in prompt.lower()

    def test_expert_basket_pluriel(self):
        prompt = expert_basket()
        assert "pluriel" in prompt.lower()
        assert "prochains matchs" in prompt
        assert "calendrier" in prompt

    def test_expert_basket_routes_plural_calendar_as_tier_1(self):
        prompt = expert_basket()
        tier_1 = prompt.split("### 🥇 Tier 1", 1)[1].split("### 🥈 Tier 2", 1)[0]
        tier_3 = prompt.split("### 🥉 Tier 3", 1)[1].split("## 🛡️", 1)[0]

        assert "ffbb_club(action='calendrier')" in tier_1
        assert "ffbb_club(action='calendrier')" not in tier_3

    def test_expert_basket_resolves_team_before_requesting_clarification(self):
        prompt = expert_basket()

        assert "appeler d'abord `ffbb_resolve_team`" in prompt
        assert 'Si `status="ambiguous"`' in prompt
        assert (
            "Catégorie ambiguë (genre ou numéro) → demander AVANT d'appeler"
            not in prompt
        )

    def test_expert_basket_limits_raw_poule_to_poule_scoped_requests(self):
        prompt = expert_basket()

        assert "Réserver `ffbb_get(type='poule')`" in prompt
        assert "Récupérer la poule brute" not in prompt

    def test_expert_basket_handles_requested_phase_explicitly(self):
        prompt = expert_basket()

        assert "Si une phase précise est demandée" in prompt
        assert "répondre directement" not in prompt

    def test_expert_basket_keeps_postponed_matches_when_filtering_calendar(self):
        prompt = expert_basket()

        assert "played == false" in prompt
        assert 'joue` vaut `0`, `"0"` ou `null`' in prompt

    def test_expert_basket_keeps_upstream_sources_behind_mcp_tools(self):
        prompt = expert_basket()

        assert "champs retournés par les outils MCP" in prompt
        assert "TOUS les appels MCP" in prompt
        assert "doivent venir des outils MCP" in prompt
        assert "TOUS les appels API" not in prompt
        assert "retournés par l'API" not in prompt

    def test_expert_basket_mentions_freshness_meta(self):
        prompt = expert_basket()
        assert "_meta.generated_at" in prompt
        assert "_meta.timezone" in prompt
        assert "force_refresh=true" in prompt

    def test_calendrier_equipe_filters_remaining_matches(self):
        prompt = calendrier_equipe("Vichy", "U13M", numero_equipe=2)
        assert "ffbb_resolve_team" in prompt
        assert "played == false" in prompt
        assert "date croissante" in prompt
        assert "numero_equipe=2" in prompt

    def test_routing_prompt_classement_lucidite(self):
        assert "CLASSEMENT & LUCIDITÉ SPORTIVE" in ROUTING_PROMPT
        assert "matchs joués ≤ 5" in ROUTING_PROMPT
        assert "INTERDICTION FORMELLE" in ROUTING_PROMPT

    def test_expert_basket_prompt_classement_lucidite(self):
        prompt = expert_basket()
        assert "Lucidité début de saison" in prompt
        assert "match_joues <= 5" in prompt
        assert "Pas d'extrapolation prédictive" in prompt

    def test_classement_poule_prompt_anti_speculation(self):
        prompt = classement_poule("NM2")
        assert "sans spéculer sur l'issue finale" in prompt
        assert "≤ 5 matchs joués" in prompt

    def test_routing_prompt_zero_slop(self):
        assert "STYLE DIRECT (ZERO-SLOP)" in ROUTING_PROMPT
        assert "Zéro politesse" in ROUTING_PROMPT

    def test_expert_basket_prompt_zero_slop(self):
        prompt = expert_basket()
        assert "zéro politesse creuse ni préambule" in prompt
        assert "Pas de verbiage de remplissage" in prompt
