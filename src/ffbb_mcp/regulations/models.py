"""Modèles de données pour les règlements FFBB et départementaux."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegulationArticle(BaseModel):
    """Représentation structurée d'un article de règlement."""

    id: str = Field(
        ...,
        description="Identifiant unique de l'article (ex: rsg_ffbb_2026_2027_art_28)",
    )
    document_id: str = Field(
        ..., description="ID du document source (ex: rsg_ffbb_2026_2027)"
    )
    season: str = Field(..., description="Saison sportive (ex: 2026-2027)")
    level: str = Field(..., description="Niveau (federal, regional, departmental)")
    organizer: str = Field(
        ..., description="Organisme responsable (FFBB, Ligue AURA, Comité 63)"
    )
    categories: list[str] = Field(
        default_factory=list,
        description="Catégories concernées (U13, U15, seniors, toutes...)",
    )
    article_number: str = Field(
        ..., description="Numéro de l'article (ex: Article 28, Article 4.1)"
    )
    article_title: str = Field(..., description="Titre de l'article")
    content: str = Field(..., description="Contenu texte complet de l'article")
    topics: list[str] = Field(
        default_factory=list, description="Thématiques et mots-clés associés"
    )
    source_url: str | None = Field(None, description="URL source officielle")


class RegulationSearchResult(BaseModel):
    """Résultat de recherche dans les règlements avec score de pertinence."""

    article: RegulationArticle
    score: float = Field(0.0, description="Score de pertinence BM25")
    matched_terms: list[str] = Field(
        default_factory=list, description="Termes trouvés dans l'article"
    )


class DocumentManifestEntry(BaseModel):
    """Entrée de document dans le manifeste des règlements."""

    id: str
    level: str
    organizer: str
    title: str
    source_url: str | None = None
    categories: list[str] = Field(default_factory=list)
    file: str
    topics: list[str] = Field(default_factory=list)


class RegulationsManifest(BaseModel):
    """Manifeste global des règlements déclarés."""

    season: str = "2026-2027"
    version: str = "1.0.0"
    documents: list[DocumentManifestEntry] = Field(default_factory=list)
