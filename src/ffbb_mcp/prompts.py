"""Définition des prompts MCP réutilisables."""

def register_prompts(mcp):
    """Enregistre les prompts sur l'instance FastMCP."""
    
    @mcp.prompt()
    def analyser_match(match_id: str) -> str:
        """Génère un prompt pour analyser un match spécifique."""
        return (
            f"Analyse le match avec l'ID {match_id}.\n"
            "Utilise l'outil `ffbb_search_rencontres` ou les ressources disponibles "
            "pour trouver les détails.\n"
            "Donne le contexte, les enjeux si possible, et le résultat probable ou affiché."
        )

    @mcp.prompt()
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

    @mcp.prompt()
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

    @mcp.prompt()
    def classement_poule(competition_name: str) -> str:
        """Aide à consulter le classement d'une compétition."""
        return (
            f"Je veux le classement de la compétition '{competition_name}'.\n"
            f"1. Utilise `ffbb_search_competitions` avec « {competition_name} »\n"
            "2. Puis `ffbb_get_competition` pour obtenir les poules\n"
            "3. Puis `ffbb_get_classement` pour le classement de la poule souhaitée\n"
            "4. Présente le classement sous forme de tableau."
        )

    @mcp.prompt()
    def bilan_equipe(club_name: str, categorie: str) -> str:
        """Aide à faire le bilan complet d'une équipe sur toute la saison."""
        return (
            f"Je veux le bilan complet de l'équipe '{categorie}' du club '{club_name}' "
            "sur la saison actuelle (toutes phases confondues).\n"
            f"1. Utilise `ffbb_search_organismes` avec « {club_name} » pour trouver l'ID\n"
            f"2. Utilise `ffbb_equipes_club` pour lister les engagements du club\n"
            f"3. Filtre les engagements contenant « {categorie} » dans la compétition\n"
            "4. Pour CHAQUE poule_id trouvé (Phase 1, Phase 2, Phase 3...), "
            "appelle `ffbb_get_classement` et trouve la ligne de l'équipe\n"
            "5. Cumule les matchs joués, victoires, défaites sur toutes les phases\n"
            "6. Présente un tableau par phase + un total cumulé de la saison."
        )

# Fonctions nues exposées pour les tests
def analyser_match(match_id: str) -> str:
    return (
        f"Analyse le match avec l'ID {match_id}.\n"
        "Utilise l'outil `ffbb_search_rencontres` ou les ressources disponibles "
        "pour trouver les détails.\n"
        "Donne le contexte, les enjeux si possible, et le résultat probable ou affiché."
    )

def trouver_club(club_name: str, department: str = "") -> str:
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
    return (
        f"Je veux le classement de la compétition '{competition_name}'.\n"
        f"1. Utilise `ffbb_search_competitions` avec « {competition_name} »\n"
        "2. Puis `ffbb_get_competition` pour obtenir les poules\n"
        "3. Puis `ffbb_get_classement` pour le classement de la poule souhaitée\n"
        "4. Présente le classement sous forme de tableau."
    )

def bilan_equipe(club_name: str, categorie: str) -> str:
    return (
        f"Je veux le bilan complet de l'équipe '{categorie}' du club '{club_name}' "
        "sur la saison actuelle (toutes phases confondues).\n"
        f"1. Utilise `ffbb_search_organismes` avec « {club_name} » pour trouver l'ID\n"
        f"2. Utilise `ffbb_equipes_club` pour lister les engagements du club\n"
        f"3. Filtre les engagements contenant « {categorie} » dans la compétition\n"
        "4. Pour CHAQUE poule_id trouvé (Phase 1, Phase 2, Phase 3...), "
        "appelle `ffbb_get_classement` et trouve la ligne de l'équipe\n"
        "5. Cumule les matchs joués, victoires, défaites sur toutes les phases\n"
        "6. Présente un tableau par phase + un total cumulé de la saison."
    )
