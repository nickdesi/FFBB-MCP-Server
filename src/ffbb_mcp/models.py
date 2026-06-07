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


class BilanResponse(BaseModel):
    """Réponse structurée et typée pour le bilan d'une équipe."""

    club: str = Field(description="Nom officiel du club.")
    categorie: str = Field(description="Catégorie d'âge/genre.")
    bilan_total: BilanTotal = Field(description="Totaux cumulés toutes phases.")
    phase_courante: PhaseBilan | None = Field(
        default=None, description="Détails de la dernière phase en cours."
    )
    equipes_bilan: dict[str, Any] = Field(
        default_factory=dict, description="Bilans ventilés par numéro d'équipe."
    )
    phases: list[PhaseBilan] = Field(
        default_factory=list, description="Liste de toutes les phases jouées."
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
