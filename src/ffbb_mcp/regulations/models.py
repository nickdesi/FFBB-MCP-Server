from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field


def compute_content_hash(content: str) -> str:
    """Calcule le hash SHA-256 canonique du contenu."""
    digest = hashlib.sha256((content or "").strip().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class RegulationArticle(BaseModel):
    """Représentation structurée d'un article de règlement."""

    id: str = Field(
        ...,
        description="Identifiant unique de l'article (ex: rsg_ffbb_2026_2027_art_28)",
    )
    document_id: str = Field(
        ..., description="ID du document source (ex: rsg_ffbb_2026_2027)"
    )
    title: str | None = Field(default=None, description="Titre du document source")
    season: str = Field(..., description="Saison sportive (ex: 2026-2027)")
    level: str = Field(..., description="Niveau (federal, regional, departmental)")
    jurisdiction: str = Field(
        default="France",
        description="Juridiction territoriale (France, Région, Département)",
    )
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
    source_url: str | None = Field(
        default=None, description="URL source officielle legacy"
    )
    official_source_url: str | None = Field(
        default=None, description="URL source officielle"
    )
    source_retrieved_at: str | None = Field(
        default=None, description="Horodatage ISO de récupération de la source"
    )
    source_last_verified_at: str | None = Field(
        default=None, description="Horodatage ISO de dernière vérification officielle"
    )
    content_hash: str = Field(
        default="", description="Hash SHA-256 du contenu de l'article pour traçabilité"
    )
    is_current_for_query: bool = Field(
        default=True, description="Indique si l'article est d'actualité pour la requête"
    )
    applicability_notes: list[str] = Field(
        default_factory=list,
        description="Notes d'applicabilité, hiérarchie réglementaire et dérogations",
    )

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash and self.content:
            self.content_hash = compute_content_hash(self.content)
        if not self.official_source_url and self.source_url:
            self.official_source_url = self.source_url
        if not self.source_url and self.official_source_url:
            self.source_url = self.official_source_url


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
