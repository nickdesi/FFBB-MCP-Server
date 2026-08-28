from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class BilanTotal(BaseModel):
    """Statistiques cumulées d'une équipe (victoires, défaites, paniers)."""

    match_joues: int = Field(default=0, description="Nombre de matchs joués.")
    gagnes: int = Field(default=0, description="Nombre de matchs gagnés.")
    perdus: int = Field(default=0, description="Nombre de matchs perdus.")
    nuls: int = Field(default=0, description="Nombre de matchs nuls.")
    paniers_marques: int = Field(default=0, description="Total des paniers marqués.")
    paniers_encaisses: int = Field(
        default=0, description="Total des paniers encaissés."
    )
    difference: int = Field(
        default=0, description="Différence de paniers (marqués - encaissés)."
    )


class PhaseBilan(BaseModel):
    """Bilan détaillé pour une phase de compétition spécifique."""

    competition: str = Field(description="Nom de la compétition.")
    poule_id: str = Field(description="ID de la poule.")
    numero_equipe: str | None = Field(
        default=None, description="Numéro de l'équipe (ex: '1', '2')."
    )
    position: int | None = Field(
        default=None, description="Position actuelle au classement."
    )
    total_equipes: int | None = Field(
        default=None, description="Nombre total d'équipes dans la poule."
    )
    phase_type: str = Field(
        default="poule", description="Type de phase (poule ou élimination)."
    )
    phase_terminee: bool = Field(
        default=False, description="Indique si la phase est terminée."
    )
    match_joues: int = Field(default=0, description="Matchs joués dans cette phase.")
    gagnes: int = Field(default=0, description="Matchs gagnés.")
    perdus: int = Field(default=0, description="Matchs perdus.")
    nuls: int = Field(default=0, description="Matchs nuls.")
    paniers_marques: int = Field(default=0, description="Paniers marqués.")
    paniers_encaisses: int = Field(default=0, description="Paniers encaissés.")
    difference: int = Field(default=0, description="Différence de paniers.")


class MatchForme(BaseModel):
    """Détail d'un match pris en compte dans la forme récente."""

    date: str | None = Field(default=None, description="Date et heure du match.")
    adversaire: str | None = Field(default=None, description="Nom de l'adversaire.")
    resultat: str = Field(description="'V' (Victoire), 'D' (Défaite) ou 'N' (Nul).")
    score: str = Field(description="Score du match (ex: '78 - 65').")
    score_pour: int | None = Field(default=None, description="Points marqués.")
    score_contre: int | None = Field(default=None, description="Points encaissés.")
    ecart: int = Field(default=0, description="Différence de points (+13 ou -8).")
    domicile: bool = Field(
        default=True, description="True si domicile, False si déplacement."
    )
    salle: str | None = Field(default=None, description="Nom de la salle.")
    journee: str | None = Field(default=None, description="Nom ou numéro de journée.")


class SerieEnCours(BaseModel):
    """Série actuelle de victoires, défaites ou invincibilité."""

    type: str = Field(
        default="aucune",
        description="'victoires', 'defaites', 'nuls' ou 'aucune'.",
    )
    count: int = Field(
        default=0, description="Nombre de matchs consécutifs dans la série."
    )
    label: str = Field(
        default="",
        description="Description lisible (ex: '3 victoires consécutives').",
    )


class FormeRecente(BaseModel):
    """Indicateur complet de dynamique et de forme récente (5 derniers matchs)."""

    forme: list[str] = Field(
        default_factory=list,
        description="Résultats des 5 derniers matchs par ordre chronologique (ex: ['V', 'V', 'D', 'V', 'V']).",
    )
    forme_str: str = Field(
        default="",
        description="Représentation texte compacte de la forme (ex: 'V-V-D-V-V').",
    )
    matchs: list[MatchForme] = Field(
        default_factory=list,
        description="Détail des matchs récents analysés.",
    )
    serie_actuelle: SerieEnCours = Field(
        default_factory=SerieEnCours,
        description="Série globale en cours toutes compétitions.",
    )
    serie_domicile: SerieEnCours = Field(
        default_factory=SerieEnCours,
        description="Série en cours pour les matchs à domicile.",
    )
    serie_exterieur: SerieEnCours = Field(
        default_factory=SerieEnCours,
        description="Série en cours pour les matchs à l'extérieur.",
    )
    victoires_5_derniers: int = Field(
        default=0, description="Nombre de victoires sur les 5 derniers matchs."
    )
    defaites_5_derniers: int = Field(
        default=0, description="Nombre de défaites sur les 5 derniers matchs."
    )
    nuls_5_derniers: int = Field(
        default=0, description="Nombre de nuls sur les 5 derniers matchs."
    )
    ratio_victoires_5_derniers: float = Field(
        default=0.0,
        description="Pourcentage de victoires sur les 5 derniers matchs (0-100%).",
    )
    pts_marques_moyenne_5: float = Field(
        default=0.0,
        description="Moyenne de points marqués par match sur les 5 derniers matchs.",
    )
    pts_encaisses_moyenne_5: float = Field(
        default=0.0,
        description="Moyenne de points encaissés par match sur les 5 derniers matchs.",
    )
    diff_moyenne_5: float = Field(
        default=0.0,
        description="Différentiel moyen de points sur les 5 derniers matchs.",
    )
    meilleure_victoire: str | None = Field(
        default=None,
        description="Plus large victoire récente (ex: '+24 vs ASPTT (84-60)').",
    )
    pire_defaite: str | None = Field(
        default=None,
        description="Plus lourde défaite récente (ex: '-12 vs US Chauriat (62-74)').",
    )
    tendance: str = Field(
        default="Stable ➡️",
        description="Tendance de la forme ('En hausse ↗️', 'Stable ➡️', 'En baisse ↘️').",
    )


class BilanResponse(BaseModel):
    """Réponse structurée et typée pour le bilan d'une équipe."""

    club: str = Field(description="Nom officiel du club.")
    categorie: str = Field(description="Catégorie d'âge/genre.")
    bilan_total: BilanTotal = Field(description="Totaux cumulés toutes phases.")
    phase_courante: PhaseBilan | None = Field(
        default=None, description="Détails de la dernière phase en cours."
    )
    saison_terminee: bool = Field(
        default=True,
        description="Indique si la saison est terminée pour cette équipe (toutes les phases jouées).",
    )
    competitions_incluses: list[str] = Field(
        default_factory=list,
        description="Liste des noms de compétitions incluses dans le bilan.",
    )
    equipes_bilan: dict[str, Any] = Field(
        default_factory=dict, description="Bilans ventilés par numéro d'équipe."
    )
    phases: list[PhaseBilan] = Field(
        default_factory=list, description="Liste de toutes les phases jouées."
    )
    dynamique: FormeRecente | None = Field(
        default=None,
        description="Dynamique et forme récente de l'équipe principale sur les 5 derniers matchs.",
    )
    profil_avance: dict[str, Any] | None = Field(
        default=None,
        description="Profil tactique avancé : rangs attaque/défense, style de jeu, clutch index et bilans domicile/extérieur.",
    )
    meta: dict[str, Any] = Field(
        default_factory=dict,
        alias="_meta",
        description="Métadonnées de fraîcheur et de cache.",
    )


class CalendrierMatch(BaseModel):
    """Structure de données typée représentant un match de calendrier."""

    id: int | str = Field(description="ID unique de la rencontre.")
    date: str | None = Field(
        default=None, description="Date et heure du match en ISO format."
    )
    joue: int | bool | None = Field(
        default=None,
        description="Indique si le match a été joué (1 ou True) ou non (0 ou False).",
    )
    equipe1: str | None = Field(
        default=None, description="Nom de l'équipe 1 (domicile)."
    )
    equipe2: str | None = Field(
        default=None, description="Nom de l'équipe 2 (extérieur)."
    )
    score_equipe1: int | None = Field(default=None, description="Score de l'équipe 1.")
    score_equipe2: int | None = Field(default=None, description="Score de l'équipe 2.")
    competition_nom: str = Field(
        default="", description="Nom de la compétition associée."
    )
    competition_type: str = Field(
        default="poule",
        description="Type de phase (poule ou élimination).",
    )
    num_journee: int | str = Field(
        default="", description="Numéro de la journée de championnat."
    )
    salle: str | dict[str, Any] | None = Field(
        default=None,
        description="Nom de la salle de sport ou dictionnaire d'informations.",
    )
    ville: str | None = Field(default=None, description="Ville où se situe la salle.")
    adresse: str | None = Field(
        default=None, description="Adresse complète de la salle."
    )
    salle_details: dict[str, Any] | None = Field(
        default=None, description="Détails enrichis de la salle de sport."
    )
    adresse_salle: str | None = Field(default=None, description="Adresse de la salle.")
    nom_salle: str | None = Field(
        default=None, description="Nom de la salle (libelle)."
    )
    lieu_complet: str | None = Field(
        default=None,
        description="Adresse formatée complète : 'Nom Salle - Adresse, CP Ville'.",
    )
    played: bool = Field(
        default=False, description="Indique si le match est déjà joué."
    )
    is_last_match: bool = Field(
        default=False, description="Indique s'il s'agit du dernier match joué."
    )
    is_next_match: bool = Field(
        default=False, description="Indique s'il s'agit du prochain match à venir."
    )

    @field_validator("score_equipe1", "score_equipe2", "joue", mode="before")
    @classmethod
    def clean_scores(cls, v: Any) -> Any:
        if v == "None" or v == "null" or v == "":
            return None
        return v
