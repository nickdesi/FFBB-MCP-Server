from pydantic import BaseModel, ConfigDict, Field


class SearchInput(BaseModel):
    """Paramètres de recherche FFBB."""

    model_config = ConfigDict(
        str_strip_whitespace=True, extra="forbid", populate_by_name=True
    )
    name: str = Field(
        ...,
        alias="nom",
        description="Terme de recherche (ex: 'Vichy', 'Pro B', 'Astroballe')",
        min_length=1,
        max_length=200,
    )


class CompetitionIdInput(BaseModel):
    """Identifiant d'une compétition FFBB."""

    model_config = ConfigDict(extra="forbid")
    competition_id: int = Field(
        ...,
        description=(
            "ID numérique de la compétition (obtenu via ffbb_search_competitions)"
        ),
        ge=1,
    )


class PouleIdInput(BaseModel):
    """Identifiant d'une poule/groupe."""

    model_config = ConfigDict(extra="forbid")
    poule_id: int = Field(
        ...,
        description="ID numérique de la poule (obtenu via ffbb_get_competition)",
        ge=1,
    )


class OrganismeIdInput(BaseModel):
    """Identifiant d'un organisme/club FFBB."""

    model_config = ConfigDict(extra="forbid")
    organisme_id: int = Field(
        ...,
        description="ID numérique de l'organisme (obtenu via ffbb_search_organismes)",
        ge=1,
    )


class SaisonsInput(BaseModel):
    """Paramètres de récupération des saisons."""

    model_config = ConfigDict(extra="forbid")
    active_only: bool = Field(
        default=False,
        description="Si True, retourne uniquement les saisons actives",
    )


class CalendrierClubInput(BaseModel):
    """Paramètres pour récupérer le calendrier d'un club."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    club_name: str = Field(
        ...,
        description="Nom du club (ex: 'Stade Clermontois', 'ASVEL')",
        min_length=1,
        max_length=200,
    )
    categorie: str = Field(
        default="",
        description="Catégorie optionnelle (ex: 'U11M', 'Seniors F', 'U13F')",
        max_length=50,
    )
