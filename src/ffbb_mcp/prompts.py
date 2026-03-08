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
        "## Workflow recommandé\n\n"
        "### 🏆 Pour le CALENDRIER (matchs à venir) et RÉSULTATS (scores passés)\n"
        "1. Utilise **TOUJOURS** `ffbb_calendrier_club` avec le nom du club et la catégorie.\n"
        "   - Ce tool a été spécialement conçu et optimisé pour récupérer TOUS les matchs "
        "(passés avec scores, et futurs) de manière fiable.\n"
        "   - Tu obtiens instantanément toute la liste des rencontres.\n\n"
        "### 🏆 Pour le CLASSEMENT d'une équipe\n"
        "1. Trouve l'organisme_id du club → `search_organismes` ou `multi_search`\n"
        "2. Liste ses équipes → `ffbb_equipes_club(organisme_id, filtre=categorie)` "
        "— chaque équipe a un `poule_id`\n"
        "3. Récupère le classement → `ffbb_get_classement(poule_id)`\n\n"
        "### Autres outils\n"
        "- Recherche générale → `multi_search` (clubs, compétitions, salles, etc.)\n"
        "- Détails compétition → `ffbb_get_competition` → liste les poules\n"
        "- Scores live → `ffbb_get_lives` (données en temps réel toutes les 30s)\n\n"
        "## Règles de comportement\n\n"
        "- Appelle TOUJOURS un outil MCP avant de répondre à toute question sur le basket français.\n"
        "- Si une recherche retourne plusieurs clubs/compétitions, liste les résultats et "
        "demande à l'utilisateur de confirmer lequel.\n"
        "- Réponds toujours en français."
    )


def analyser_match(match_id: str) -> str:
    """Génère un prompt pour analyser un match spécifique."""
    return (
        f"Analyse le match avec l'ID {match_id}.\n"
        "Utilise l'outil `ffbb_search_rencontres` ou les ressources disponibles "
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
        "1. Utilise `ffbb_search_organismes` pour trouver l'ID du club\n"
        "2. Puis `ffbb_get_organisme` pour les détails complets\n"
        "3. Liste son adresse et ses équipes engagées cette saison."
    )


def prochain_match(club_name: str, categorie: str = "") -> str:
    """Aide à trouver le prochain match d'un club."""
    query = club_name
    if categorie:
        query += f" {categorie}"
    return (
        f"Je cherche le prochain match de '{query}'.\n"
        f"1. Utilise `ffbb_calendrier_club` avec club_name='{club_name}'"
        + (f" et categorie='{categorie}'" if categorie else "")
        + "\n"
        "2. Filtre les résultats pour ne garder que les matchs à venir\n"
        "3. Donne la date, l'heure, l'adversaire et le lieu du prochain match."
    )


def classement_poule(competition_name: str) -> str:
    """Aide à consulter le classement d'une compétition."""
    return (
        f"Je veux le classement de la compétition '{competition_name}'.\n"
        f"1. Utilise `ffbb_search_competitions` avec « {competition_name} »\n"
        "2. Puis `ffbb_get_competition` pour obtenir les poules\n"
        "3. Puis `ffbb_get_classement` pour le classement de la poule souhaitée\n"
        "4. Présente le classement sous forme de tableau."
    )


def bilan_equipe(club_name: str, categorie: str) -> str:
    """Aide à faire le bilan complet d'une équipe sur toute la saison."""
    return (
        f"Je veux le bilan complet de l'équipe '{categorie}' du club '{club_name}' "
        "sur la saison actuelle (toutes phases confondues).\n"
        f"1. Si l'équipe demandée est ambiguë (ex: manque le genre M/F ou le numéro d'équipe 1/2), "
        "DEMANDE une précision au user.\n"
        f"2. Utilise `ffbb_search_organismes` avec « {club_name} » pour trouver l'ID\n"
        f"3. Utilise `ffbb_equipes_club` pour lister les engagements du club\n"
        f"4. Filtre les engagements contenant « {categorie} » dans la compétition\n"
        "5. Pour CHAQUE poule_id trouvé (Phase 1, Phase 2, Phase 3...), appelle "
        "`ffbb_get_classement` et trouve la ligne de LA BONNE équipe (croise les adversaires "
        "pour être sûr de ne pas sauter d'Équipe 1 à Équipe 2).\n"
        "6. Cumule les matchs joués, victoires, défaites sur toutes les phases\n"
        "7. Présente un tableau par phase + un total cumulé de la saison."
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
