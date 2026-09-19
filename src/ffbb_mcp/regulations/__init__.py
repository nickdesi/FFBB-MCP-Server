"""Module des règlements sportifs FFBB, régionaux et départementaux."""

from .applicability import (
    LOCAL_NOT_INDEXED_WARNING,
    OFFICIAL_DISCLAIMER,
    is_sensitive_topic,
    resolve_applicable_regulations,
)
from .engine import RegulationsEngine, get_regulations_engine
from .indexer import index_manifest, parse_markdown_document
from .models import (
    DocumentManifestEntry,
    RegulationArticle,
    RegulationSearchResult,
    RegulationsManifest,
)

__all__ = [
    "LOCAL_NOT_INDEXED_WARNING",
    "OFFICIAL_DISCLAIMER",
    "DocumentManifestEntry",
    "RegulationArticle",
    "RegulationSearchResult",
    "RegulationsEngine",
    "RegulationsManifest",
    "get_regulations_engine",
    "index_manifest",
    "is_sensitive_topic",
    "parse_markdown_document",
    "resolve_applicable_regulations",
]
