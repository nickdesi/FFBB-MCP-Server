"""Module des règlements sportifs FFBB, régionaux et départementaux."""

from .engine import RegulationsEngine, get_regulations_engine
from .indexer import index_manifest, parse_markdown_document
from .models import (
    DocumentManifestEntry,
    RegulationArticle,
    RegulationSearchResult,
    RegulationsManifest,
)

__all__ = [
    "DocumentManifestEntry",
    "RegulationArticle",
    "RegulationSearchResult",
    "RegulationsEngine",
    "RegulationsManifest",
    "get_regulations_engine",
    "index_manifest",
    "parse_markdown_document",
]
