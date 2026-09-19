"""Moteur d'applicabilité et de hiérarchie des règlements sportifs FFBB."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Any

from .engine import RegulationsEngine, get_regulations_engine

if TYPE_CHECKING:
    from .models import RegulationArticle

OFFICIAL_DISCLAIMER = (
    "Information réglementaire indicative issue des documents indexés. "
    "Pour une décision officielle, vérifier le règlement applicable de la saison, "
    "les éventuelles dispositions territoriales et la commission compétente."
)

LOCAL_NOT_INDEXED_WARNING = (
    "Règlement local non indexé : vérification nécessaire auprès de l'organisateur."
)

SENSITIVE_TOPICS = {
    "licence",
    "licences",
    "qualification",
    "qualifications",
    "mutation",
    "mutations",
    "brulage",
    "brûlage",
    "forfait",
    "forfaits",
    "penalite",
    "pénalité",
    "penalites",
    "pénalités",
    "reclamation",
    "réclamation",
    "reclamations",
    "réclamations",
    "surclassement",
    "sanction",
    "sanctions",
    "accession",
    "relegation",
    "relégation",
    "departage",
    "départage",
}

HIERARCHY_LEVELS = {
    "federal": 1,
    "regional": 2,
    "departmental": 3,
}


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    ).lower()


def is_sensitive_topic(text: str) -> bool:
    """Détecte si le texte ou la requête aborde une thématique réglementaire sensible."""
    norm = _strip_accents(text)
    words = set(re.findall(r"\w+", norm))
    return bool(words.intersection({_strip_accents(t) for t in SENSITIVE_TOPICS}))


def resolve_applicable_regulations(
    context: dict[str, Any],
    query: str | None = None,
    engine: RegulationsEngine | None = None,
) -> dict[str, Any]:
    """Résout et ordonne les règlements applicables selon la hiérarchie officielle FFBB.

    Hiérarchie métier :
    1. Règlement Sportif Général FFBB (fédéral)
    2. Règlement Sportif Particulier fédéral (fédéral)
    3. Règlement de Ligue Régionale (régional)
    4. Règlement de Comité Départemental (départemental)
    5. Dérogation officiellement documentée

    Args:
        context: Dictionnaire de contexte (season, level, organizer, region,
                 departement, categorie, sexe, competition_type).
        query: Requête ou terme de recherche réglementaire optionnel.
        engine: Instance optionnelle de RegulationsEngine (défaut: shared singleton).

    Returns:
        Dictionnaire structuré avec articles, avertissements, métadonnées et disclaimers.
    """
    if engine is None:
        engine = get_regulations_engine()

    season = context.get("season", "2026-2027")
    organizer = context.get("organizer")
    region = context.get("region")
    departement = context.get("departement") or context.get("comite")
    requested_level = context.get("level")

    # Vérification des documents indexés
    available_docs = engine.list_available_documents(season=season)
    available_organizers = {
        _strip_accents(d["organizer"]) for d in available_docs if d.get("organizer")
    }

    warnings: list[str] = []
    has_local_demand = bool(
        departement or region or (organizer and "ffbb" not in _strip_accents(organizer))
    )

    # Vérifier si l'organisateur local demandé est indexé
    local_found = False
    if has_local_demand:
        for org in available_organizers:
            if (
                (departement and _strip_accents(str(departement)) in org)
                or (region and _strip_accents(str(region)) in org)
                or (organizer and _strip_accents(str(organizer)) in org)
            ):
                local_found = True
                break

        if not local_found:
            warnings.append(LOCAL_NOT_INDEXED_WARNING)

    # Récupérer les articles correspondants
    articles: list[RegulationArticle] = []
    if query:
        search_res = engine.search(
            query=query,
            season=season,
            level=requested_level,
            organizer=organizer,
            category=context.get("categorie"),
            limit=10,
        )
        for sr in search_res:
            articles.append(sr.article)

    # Si aucun article par recherche ou query absente, chercher les articles de fond
    if not articles and not query:
        raw_list = engine.list_available_documents(season=season)
        for doc_info in raw_list:
            doc_id = doc_info["document_id"]
            art = engine.get_article(document_id=doc_id, season=season)
            if art:
                articles.append(art)

    # Tri selon la hiérarchie des normes FFBB (fédéral > régional > départemental)
    def _hierarchy_key(art: RegulationArticle) -> tuple[int, str]:
        lvl = art.level.lower() if art.level else "federal"
        rank = HIERARCHY_LEVELS.get(lvl, 99)
        return (rank, art.organizer or "")

    articles.sort(key=_hierarchy_key)

    # Vérification des sujets sensibles
    full_text = f"{query or ''} {' '.join((art.content or '') + ' ' + (art.article_title or '') for art in articles)}"
    is_sensitive = is_sensitive_topic(full_text)
    if is_sensitive:
        warnings.append(OFFICIAL_DISCLAIMER)

    # Annoter chaque article avec ses notes d'applicabilité
    for art in articles:
        notes = list(art.applicability_notes)
        lvl_desc = {
            "federal": "Norme fédérale nationale prioritaire (RSG FFBB).",
            "regional": "Règlement régional pouvant préciser les dispositions fédérales.",
            "departmental": "Règlement départemental spécifique au comité.",
        }.get(art.level.lower(), "Règlement applicable.")
        if lvl_desc not in notes:
            notes.append(lvl_desc)
        if (
            warnings
            and LOCAL_NOT_INDEXED_WARNING in warnings
            and art.level.lower() == "federal"
        ):
            warn_msg = "Dispositions locales non vérifiées ; sous réserve de dérogations territoriales."
            if warn_msg not in notes:
                notes.append(warn_msg)
        art.applicability_notes = notes

    return {
        "status": "ok",
        "season": season,
        "hierarchy_order": [
            "1. Règlement Sportif Général FFBB (fédéral)",
            "2. Règlement Sportif Particulier fédéral (fédéral)",
            "3. Règlement de Ligue Régionale (régional)",
            "4. Règlement de Comité Départemental (départemental)",
            "5. Dérogation officiellement documentée",
        ],
        "context": context,
        "articles": [art.model_dump() for art in articles],
        "warnings": warnings,
        "is_sensitive_topic": is_sensitive,
        "disclaimer": OFFICIAL_DISCLAIMER if is_sensitive else None,
    }
