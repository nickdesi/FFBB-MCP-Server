from typing import Any

from pydantic import BaseModel


class Competition(BaseModel):
    id: int
    libelle: str
    type: str
    saison: str
    organisateur: str | None = None


class Organisme(BaseModel):
    id: int
    libelle: str
    type: str
    adresse: str | None = None
    code_postal: str | None = None
    ville: str | None = None


class Rencontre(BaseModel):
    id: int
    competition: str
    equipe_domicile: str
    equipe_exterieur: str
    score_domicile: int | None = None
    score_exterieur: int | None = None
    statut: str
    date: str


class Salle(BaseModel):
    id: int
    libelle: str
    adresse: str
    ville: str
    capacite: int | None = None


class MultiSearchResult(BaseModel):
    id: int
    libelle: str
    type: str  # Competition, Organisme, Rencontre, etc.
    details: dict[str, Any]
