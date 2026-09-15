"""Services métier pour la consultation et l'explication des règlements FFBB."""

from __future__ import annotations

import logging
from typing import Any

from ffbb_mcp.regulations.engine import get_regulations_engine

logger = logging.getLogger(__name__)


async def search_regulations_service(
    query: str = "",
    season: str = "2026-2027",
    level: str | None = None,
    organizer: str | None = None,
    category: str | None = None,
    topic: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Recherche dans les règlements FFBB (généraux, particuliers, régionaux, départementaux)."""
    engine = get_regulations_engine()
    results = engine.search(
        query=query,
        season=season,
        level=level,
        organizer=organizer,
        category=category,
        topic=topic,
        limit=limit,
    )

    formatted_results = []
    for r in results:
        art = r.article
        formatted_results.append(
            {
                "id": art.id,
                "document_id": art.document_id,
                "organizer": art.organizer,
                "level": art.level,
                "categories": art.categories,
                "article_number": art.article_number,
                "article_title": art.article_title,
                "content": art.content,
                "topics": art.topics,
                "source_url": art.source_url,
                "relevance_score": r.score,
            }
        )

    return {
        "season": season,
        "query": query,
        "total_results": len(formatted_results),
        "results": formatted_results,
    }


async def get_regulation_article_service(
    document_id: str | None = None,
    article_number: str | None = None,
    organizer: str | None = None,
    season: str = "2026-2027",
) -> dict[str, Any]:
    """Récupère le texte intégral d'un article spécifique de règlement."""
    engine = get_regulations_engine()
    art = engine.get_article(
        document_id=document_id,
        article_number=article_number,
        organizer=organizer,
        season=season,
    )

    if not art:
        return {
            "found": False,
            "message": f"Aucun article trouvé pour document='{document_id}', article='{article_number}', organisateur='{organizer}'",
        }

    return {
        "found": True,
        "article": {
            "id": art.id,
            "document_id": art.document_id,
            "season": art.season,
            "organizer": art.organizer,
            "level": art.level,
            "categories": art.categories,
            "article_number": art.article_number,
            "article_title": art.article_title,
            "content": art.content,
            "topics": art.topics,
            "source_url": art.source_url,
        },
    }


async def explain_tiebreak_rules_service(
    poule_id: int | None = None,
    season: str = "2026-2027",
) -> dict[str, Any]:
    """Fournit les règles de départage officielles FFBB (Article 28 du RSG) et le guide d'application."""
    engine = get_regulations_engine()
    art28 = engine.get_article(
        document_id="rsg_ffbb_2026_2027",
        article_number="Article 28",
        season=season,
    )

    return {
        "season": season,
        "regulation_source": "RSG FFBB (Article 28)",
        "summary": (
            "En cas d'égalité de points au classement FFBB :\n"
            "1. Égalité entre 2 équipes : départage au point-average particulier (confrontations directes), "
            "puis différence de points particulière, puis quotient particulier, puis point-average général.\n"
            "2. Égalité entre 3 équipes ou plus : mini-championnat entre les équipes concernées uniquement. "
            "Classement aux points, puis différence de points particulière du mini-championnat."
        ),
        "full_text": art28.content if art28 else "Article 28 non chargé.",
        "poule_id": poule_id,
    }


async def list_regulations_service(season: str = "2026-2027") -> dict[str, Any]:
    """Liste l'ensemble des juridictions et documents de règlements actuellement disponibles."""
    engine = get_regulations_engine()
    docs = engine.list_available_documents(season=season)
    return {
        "season": season,
        "scope": "national",
        "total_documents": len(docs),
        "jurisdictions": docs,
        "note": (
            "Le Règlement Sportif Général (RSG FFBB) s'applique par défaut sur tout le territoire national français. "
            "Les ligues régionales et comités départementaux le complètent avec leurs règlements particuliers respectifs."
        ),
    }
