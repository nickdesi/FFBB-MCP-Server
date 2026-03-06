from pydantic import BaseModel, ConfigDict, Field, AliasChoices
from typing import Optional, Union


class SearchInput(BaseModel):
    """
    OBSOLETE: Gardé pour compatibilité interne si besoin.
    Les outils utilisent maintenant des arguments directs.
    """
    model_config = ConfigDict(
        str_strip_whitespace=True, extra="ignore", populate_by_name=True
    )
    name: str = Field(
        ...,
        validation_alias=AliasChoices("nom", "query"),
    )


class CalendrierClubInput(BaseModel):
    """
    OBSOLETE: Gardé pour compatibilité interne si besoin.
    """
    club_name: Optional[str] = None
    organisme_id: Optional[Union[int, str]] = None
    categorie: Optional[str] = None
