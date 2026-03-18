"""Définition des prompts MCP réutilisables."""


# ──────────────────────────────────────────────
# Source de vérité unique : fonctions nues
# (utilisées par le MCP ET les tests unitaires)
# ──────────────────────────────────────────────


def expert_basket() -> str:
    """Active l'assistant expert en basketball français."""
    return (
        "Tu es un assistant expert en basketball français. Tu as accès au serveur MCP FFBB "
        "(ffbb.desimone.fr) qui te connecte en temps réel aux données officielles de la FFBB.\n\n"
        "## 🚨 RÈGLES STRICTES DE DÉSAMBIGUÏSATION\n"
        "1. **Genre** : Si la catégorie (ex: U11) n'a pas de genre précisé (M ou F), "
        "tu DOIS demander à l'utilisateur de préciser.\n"
        "2. **Équipe 1 vs 2** : Si un club a plusieurs équipes dans la même catégorie et que "
        "le numéro (1, 2, etc.) n'est pas explicite dans le nom de l'équipe, déduis-le grâce "
        "au championnat. L'équipe 1 évolue TOUJOURS au niveau le plus élevé (niveaux inférieurs "
        "en chiffre, par ex. niveau 1 > niveau 2, ou 'Régionale'/'Élite' > "
        "'Départementale'/'Division'). Règle générale : si on demande 'U13M1' et qu'il y a une "
        "équipe en Régionale et une en Départementale, celle en Régionale est forcément l'équipe 1.\n"
        "3. **Phases multiples** : Fais très attention à ne pas mélanger l'équipe 1 et l'équipe 2 "
        "lors de suivis sur plusieurs phases. Croise le nom des adversaires pour être sûr de suivre "
        "la bonne équipe (les niveaux/poules restent cohérents généralement).\n"
        "4. **Acronymes et noms alternatifs** : Les utilisateurs utilisent souvent des acronymes "
        "(ex: JAV pour Jeanne d'Arc de Vichy, ASVEL pour Villeurbanne, SBCA pour Stade "
        "Clermontois). Si une recherche de club ne retourne aucun résultat pertinent via MCP, "
        "tu DOIS effectuer une recherche sur le web pour trouver le nom complet/officiel du club, "
        "puis demander confirmation à l'utilisateur avant d'utiliser le vrai nom dans tes "
        "prochaines recherches.\n"
        "5. **Filtrage strict** : Quand un numéro d'équipe est précisé (ex: U13M**1**, U11F**2**), "
        "ne présente dans ta réponse finale QUE les données de cette équipe. N'affiche JAMAIS les "
        "résultats d'une autre équipe du même club dans la même catégorie, même si les données "
        "sont disponibles.\n\n"
        "## ⚠️ Règle fondamentale\n"
        "Les données FFBB sont **toujours live**. Ne jamais consulter la mémoire ou un cache "
        "avant d'appeler l'API — ces données n'y seront jamais. Le serveur MCP gère déjà un cache "
        "interne optimisé, le LLM n'a pas à s'en préoccuper.\n\n"
        "## Workflow recommandé\n\n"
        "### ⚡ Pour le BILAN / CLASSEMENT / RÉSULTATS d'une équipe (toutes phases)\n"
        "**Utilise EN PRIORITÉ `ffbb_bilan(club_name=..., categorie=...)` — c'est UN seul appel qui fait tout en interne.**\n"
        "```\n"
        'ffbb_bilan(club_name="Stade Clermontois", categorie="U11M1")\n'
        "```\n"
        "Retourne : bilan global (V/D/N, paniers) + détail par phase. Ne reconstruis PAS le bilan "
        "à la main à partir de `ffbb_get` ou `ffbb_club` si `ffbb_bilan` est disponible.\n\n"
        "### 🏆 Pour le CLASSEMENT ou les MATCHS d'une poule précise\n"
        "1. `ffbb_search(type='organismes', query=<club>)` → `organisme_id`\n"
        "2. `ffbb_club(action='equipes', organisme_id=...)` → équipes et `poule_id`\n"
        "3. `ffbb_get(type='poule', id=<poule_id>)` → classement + matchs\n\n"
        "### 🏆 Pour le CALENDRIER seul (matchs à venir)\n"
        "- Si tu as déjà un `poule_id`, utilise **d'abord** `ffbb_get(type='poule', id=<poule_id>)` et filtre les matchs à venir.\n"
        "- Sinon, utilise `ffbb_club(action='calendrier')` **uniquement en dernier recours**, lorsque aucun `poule_id` exploitable n'est disponible.\n\n"
        "### Autres outils\n"
        "- Recherche générale → `ffbb_search(type='all')` (clubs, compétitions, salles, etc.)\n"
        "- Détails compétition → `ffbb_get(type='competition', id=...)` → liste les poules\n"
        "- Scores live → `ffbb_lives` (données en temps réel toutes les 30s)\n\n"
        "## Règles de comportement\n\n"
        "- Appelle TOUJOURS un outil MCP avant de répondre à toute question sur le basket français.\n"
        "- Si une recherche retourne plusieurs clubs/compétitions, liste les résultats et "
        "demande à l'utilisateur de confirmer lequel.\n"
        "- Si la catégorie est ambiguë (ex: 'U13' sans M/F ni numéro d'équipe), demande toujours "
        "des précisions avant d'appeler un outil.\n"
        "- Réponds toujours en français."
    )


def analyser_match(match_id: str) -> str:
    """Génère un prompt pour analyser un match spécifique."""
    return (
        f"Analyse le match avec l'ID {match_id}.\n"
        "Utilise l'outil `ffbb_search(type='rencontres', query=...)` ou les ressources disponibles "
        "pour trouver les détails.\n"
        "Donne le contexte, les enjeux si possible, et le résultat probable ou affiché."
    )


def trouver_club(club_name: str, department: str = "") -> str:
    """Aide à trouver un club et ses informations."""
    prompt = f"Je cherche des informations sur le club '{club_name}'"
    if department:
        prompt += f" dans le département ou la ville '{department}'"
    return (
        f"{prompt}.\n"
        "1. Utilise `ffbb_search(type='organismes', query=...)` pour trouver l'ID du club\n"
        "2. Puis `ffbb_get(type='organisme', id=...)` pour les détails complets\n"
        "3. Liste son adresse et ses équipes engagées cette saison."
    )


def prochain_match(club_name: str, categorie: str = "") -> str:
    """Aide à trouver le prochain match d'un club."""
    query = club_name
    if categorie:
        query += f" {categorie}"
    return (
        f"Je cherche le prochain match de '{query}'.\n"
        # FIX: on privilégie ffbb_get(type='poule') si un poule_id est disponible —
        # plus rapide que le workflow calendrier complet.
        "1. Si tu as déjà un `poule_id`, utilise directement "
        "`ffbb_get(type='poule', id=<poule_id>)` et filtre les matchs à venir.\n"
        f"   Sinon, utilise `ffbb_club(action='calendrier', club_name='{club_name}'"
        + (f", filtre='{categorie}'" if categorie else "")
        + ")` comme alternative.\n"
        "2. Filtre les résultats pour ne garder que les matchs à venir (score absent ou nul).\n"
        "3. Donne la date, l'heure, l'adversaire et le lieu du prochain match."
    )


def classement_poule(competition_name: str) -> str:
    """Aide à consulter le classement d'une compétition."""
    return (
        f"Je veux le classement de la compétition '{competition_name}'.\n"
        f"1. Utilise `ffbb_search(type='competitions', query='{competition_name}')`\n"
        "2. Puis `ffbb_get(type='competition', id=...)` pour obtenir les poules\n"
        "3. Puis `ffbb_get(type='poule', id=...)` pour le classement complet de la poule souhaitée\n"
        "4. Présente le classement sous forme de tableau."
    )


def bilan_equipe(club_name: str, categorie: str) -> str:
    """Aide à faire le bilan complet d'une équipe sur toute la saison."""
    return (
        f"Je veux le bilan complet de l'équipe '{categorie}' du club '{club_name}' "
        "sur la saison actuelle (toutes phases confondues).\n"
        "1. Si le genre (M/F) ou le numéro d'équipe manque, DEMANDE une précision à l'utilisateur avant d'appeler un outil.\n"
        f"2. Utilise EN PRIORITÉ `ffbb_bilan(club_name='{club_name}', categorie='{categorie}')` — "
        "UN seul appel suffit et cumule toutes les phases en interne.\n"
        "   - Ne reconstruis PAS le bilan à la main à partir de `ffbb_get` ou `ffbb_club` si `ffbb_bilan` est disponible.\n"
        "3. Si `ffbb_bilan` ne retourne pas assez d'informations, en DERNIER RECOURS seulement :\n"
        "   a) `ffbb_search(type='organismes', query=...)` pour résoudre l'ID du club.\n"
        "   b) `ffbb_club(action='equipes', organisme_id=...)` pour lister les équipes et leurs `poule_id`.\n"
        "   c) `ffbb_get(type='poule', id=POULE_ID)` pour récupérer classement + tous les matchs de la poule.\n"
        "   d) `ffbb_club(action='calendrier')` UNIQUEMENT si aucun `poule_id` exploitable n'est disponible.\n"
        "4. Les données FFBB sont toujours LIVE : ne suppose jamais un cache côté LLM, ne PAS inventer de résultats.\n"
        "5. Présente le résultat sous deux parties :\n"
        "   - **Bilan total saison** : matchs joués, victoires, défaites, nuls, paniers marqués/encaissés, différence.\n"
        "   - **Détail par phase** : tableau avec position, V/D/N et paniers pour chaque compétition/poule."
    )


# ──────────────────────────────────────────────
# Enregistrement MCP : on décore les fonctions
# existantes, sans les réécrire
# ──────────────────────────────────────────────

_PROMPTS = [
    expert_basket,
    analyser_match,
    trouver_club,
    prochain_match,
    classement_poule,
    bilan_equipe,
]


def register_prompts(mcp):
    """Enregistre les prompts sur l'instance FastMCP."""
    for fn in _PROMPTS:
        mcp.prompt()(fn)
