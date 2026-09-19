"""Modèles et contrat d'enveloppe uniforme pour les réponses FFBB MCP.

Garantit un schéma homogène, traçable et résilient pour tous les outils :
- `status`: ok | ambiguous | not_found | partial | stale | unavailable | invalid_request
- `data`: payload métier typé
- `warnings`: liste de messages d'avertissement
- `errors`: liste de messages d'erreur
- `resolution`: contexte détaillé de résolution d'équipe/club/compétition
- `provenance`: métadonnées de source, cache, horodatage et saison
- `data_quality`: niveau de fiabilité et détection des conflits
- `request_id`: UUID unique par requête
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResponseStatus(StrEnum):
    """Statuts canoniques autorisés pour l'enveloppe de réponse."""

    OK = "ok"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    PARTIAL = "partial"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"


class ResolutionInfo(BaseModel):
    """Métadonnées de résolution d'équipe, club ou compétition."""

    mode: Literal["strict", "suggest", "all"] = Field(
        default="strict", description="Mode de résolution appliqué."
    )
    input: dict[str, Any] = Field(
        default_factory=dict, description="Paramètres d'entrée fournis au résolveur."
    )
    normalized: dict[str, Any] = Field(
        default_factory=dict,
        description="Valeurs d'entrée après normalisation canonique.",
    )
    selected: dict[str, Any] | None = Field(
        default=None,
        description="Engagement ou entité sélectionnée de manière univoque.",
    )
    candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Liste des candidats plausibles en cas d'ambiguïté.",
    )
    match_strategy: list[str] = Field(
        default_factory=list, description="Étapes et critères de matching appliqués."
    )
    confidence: float | None = Field(
        default=None, description="Score de confiance de la résolution (0.0 à 1.0)."
    )


class ProvenanceCache(BaseModel):
    """Métadonnées de cache pour la provenance des données."""

    hit: bool = Field(
        default=False, description="True si la réponse provient du cache."
    )
    age_seconds: int = Field(default=0, description="Âge de la donnée en secondes.")
    ttl_seconds: int = Field(default=300, description="TTL configuré en secondes.")
    stale: bool = Field(
        default=False,
        description="True si la donnée servie est périmée (fallback SWR).",
    )


class ProvenanceInfo(BaseModel):
    """Traçabilité de la provenance de la donnée sportive ou réglementaire."""

    source: str = Field(
        default="ffbb_api_live",
        description="Source de la donnée : 'ffbb_api_live', 'meilisearch', 'cache', 'regulations_index'.",
    )
    fetched_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Horodatage ISO-8601 de récupération.",
    )
    source_updated_at: str | None = Field(
        default=None,
        description="Dernière mise à jour déclarée par la source amont si disponible.",
    )
    season_id: str | None = Field(
        default=None, description="Identifiant FFBB de la saison sportive concernée."
    )
    cache: ProvenanceCache = Field(
        default_factory=ProvenanceCache, description="Détails sur l'état du cache."
    )


class DataQualityInfo(BaseModel):
    """Évaluation de la cohérence et de la qualité des données."""

    level: Literal["high", "medium", "low", "conflict"] = Field(
        default="high", description="Niveau qualitatif : high, medium, low ou conflict."
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Liste des anomalies ou contradictions détectées.",
    )
    raw_statuses: dict[str, Any] = Field(
        default_factory=dict, description="Statuts bruts remontés par l'amont."
    )
    canonical_status: str | None = Field(
        default=None,
        description="Statut canonique normalisé de la rencontre ou entité.",
    )


class McpResponseEnvelope[T](BaseModel):
    """Enveloppe uniforme et déterministe pour toutes les réponses du serveur MCP."""

    status: ResponseStatus = Field(
        default=ResponseStatus.OK, description="Statut général de la réponse."
    )
    data: T | None = Field(
        default=None, description="Données sportives ou réglementaires utiles."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Avertissements non bloquants pour le consommateur.",
    )
    errors: list[str] = Field(
        default_factory=list, description="Erreurs identifiées lors du traitement."
    )
    resolution: ResolutionInfo = Field(
        default_factory=ResolutionInfo,
        description="Détails du processus de résolution.",
    )
    provenance: ProvenanceInfo = Field(
        default_factory=ProvenanceInfo,
        description="Traçabilité et fraîcheur des données.",
    )
    data_quality: DataQualityInfo = Field(
        default_factory=DataQualityInfo,
        description="Indicateur d'intégrité de la donnée.",
    )
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Identifiant unique de la requête pour traçabilité et logs.",
    )

    # Compatibilité dictionnaire pour les clients et assertions legacy
    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def create_response_envelope(
    data: Any = None,
    status: ResponseStatus = ResponseStatus.OK,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    resolution: ResolutionInfo | None = None,
    provenance: ProvenanceInfo | None = None,
    data_quality: DataQualityInfo | None = None,
    request_id: str | None = None,
) -> McpResponseEnvelope[Any]:
    """Fabrique une enveloppe de réponse MCP standardisée."""
    return McpResponseEnvelope[Any](
        status=status,
        data=data,
        warnings=warnings or [],
        errors=errors or [],
        resolution=resolution or ResolutionInfo(),
        provenance=provenance or ProvenanceInfo(),
        data_quality=data_quality or DataQualityInfo(),
        request_id=request_id or str(uuid.uuid4()),
    )


def create_ambiguous_envelope(
    candidates: list[dict[str, Any]],
    message: str,
    input_data: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> McpResponseEnvelope[Any]:
    """Fabrique une enveloppe pour une requête ambiguë (aucune extrapolation permise)."""
    return McpResponseEnvelope[Any](
        status=ResponseStatus.AMBIGUOUS,
        data=None,
        warnings=[message],
        resolution=ResolutionInfo(
            mode="strict",
            input=input_data or {},
            candidates=candidates,
            match_strategy=["ambiguous_candidates_detected"],
        ),
        data_quality=DataQualityInfo(level="medium"),
        request_id=request_id or str(uuid.uuid4()),
    )


def create_not_found_envelope(
    message: str,
    suggestions: list[dict[str, Any]] | list[str] | None = None,
    input_data: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> McpResponseEnvelope[Any]:
    """Fabrique une enveloppe lorsque la ressource ou l'engagement n'est pas trouvé."""
    norm_candidates: list[dict[str, Any]] = []
    if suggestions:
        for s in suggestions:
            if isinstance(s, dict):
                norm_candidates.append(s)
            else:
                norm_candidates.append({"label": str(s)})

    return McpResponseEnvelope[Any](
        status=ResponseStatus.NOT_FOUND,
        data=None,
        warnings=[message],
        resolution=ResolutionInfo(
            mode="strict",
            input=input_data or {},
            candidates=norm_candidates,
            match_strategy=["no_exact_match_found"],
        ),
        data_quality=DataQualityInfo(level="low"),
        request_id=request_id or str(uuid.uuid4()),
    )
