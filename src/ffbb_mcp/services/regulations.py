"""Services métier pour la consultation et l'explication des règlements FFBB."""

from __future__ import annotations

import contextlib
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


def _normalize_team_for_h2h(name: str) -> str:
    import re

    return re.sub(r"\s+-\s+\d+$", "", name.strip().upper())


def _analyze_poule_tiebreaks(
    poule_info: dict[str, Any],
    classements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rencontres = poule_info.get("rencontres") or []

    played_matches: list[dict[str, Any]] = []
    for r in rencontres:
        sc1 = r.get("resultatEquipe1")
        sc2 = r.get("resultatEquipe2")
        if (
            sc1 is not None
            and sc2 is not None
            and str(sc1).isdigit()
            and str(sc2).isdigit()
        ):
            played_matches.append(
                {
                    "id": r.get("id"),
                    "equipe1": r.get("nomEquipe1") or "",
                    "score1": int(sc1),
                    "equipe2": r.get("nomEquipe2") or "",
                    "score2": int(sc2),
                    "journee": r.get("numeroJournee"),
                }
            )

    from collections import defaultdict

    points_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for c in classements:
        pts = c.get("points")
        if pts is not None:
            with contextlib.suppress(ValueError, TypeError):
                points_groups[int(pts)].append(c)

    tiebreak_groups: list[dict[str, Any]] = []
    for pts in sorted(points_groups.keys(), reverse=True):
        teams = points_groups[pts]
        if len(teams) <= 1:
            continue

        teams = sorted(teams, key=lambda t: t.get("position") or 999)
        team_names = [t.get("equipe") or t.get("nom") or "" for t in teams]

        h2h_matches: list[dict[str, Any]] = []
        for m in played_matches:
            m1 = m["equipe1"]
            m2 = m["equipe2"]
            in_group_1 = any(
                t == m1 or _normalize_team_for_h2h(t) == _normalize_team_for_h2h(m1)
                for t in team_names
            )
            in_group_2 = any(
                t == m2 or _normalize_team_for_h2h(t) == _normalize_team_for_h2h(m2)
                for t in team_names
            )
            if in_group_1 and in_group_2:
                h2h_matches.append(m)

        expected_pairs = len(teams) * (len(teams) - 1) // 2

        if len(teams) == 2:
            eq_a = teams[0].get("equipe") or teams[0].get("nom")
            eq_b = teams[1].get("equipe") or teams[1].get("nom")
            diff_a = teams[0].get("difference", 0)
            diff_b = teams[1].get("difference", 0)
            if h2h_matches:
                m = h2h_matches[0]
                status = "confrontation_directe_jouee"
                if (m["equipe1"] == eq_a and m["score1"] > m["score2"]) or (
                    m["equipe2"] == eq_a and m["score2"] > m["score1"]
                ):
                    score_txt = (
                        f"{m['score1']}-{m['score2']}"
                        if m["equipe1"] == eq_a
                        else f"{m['score2']}-{m['score1']}"
                    )
                    explication = (
                        f"Égalité à 2 équipes ({pts} pts) : {eq_a} devance {eq_b} au point-average particulier "
                        f"suite à sa victoire ({score_txt}) lors de la confrontation directe (Article 28 du RSG)."
                    )
                else:
                    explication = (
                        f"Égalité à 2 équipes ({pts} pts) : {len(h2h_matches)} confrontation(s) directe(s) jouée(s). "
                        f"Départage au point-average particulier conformément à l'Article 28 du RSG."
                    )
            else:
                status = "departage_provisoire_difference_generale"
                explication = (
                    f"Égalité à 2 équipes ({pts} pts) : aucune confrontation directe jouée à ce jour entre "
                    f"{eq_a} et {eq_b}. Départage provisoire à la différence de points générale "
                    f"({diff_a:+d} contre {diff_b:+d})."
                )
        else:
            status = "mini_championnat"
            unit_pts = "pt" if pts <= 1 else "pts"
            if len(h2h_matches) >= expected_pairs:
                explication = (
                    f"Égalité multiple ({len(teams)} équipes à {pts} {unit_pts}) : mini-championnat complet "
                    f"({len(h2h_matches)} matchs joués). Classement aux points particuliers, "
                    f"puis point-average particulier du mini-championnat."
                )
            elif h2h_matches:
                explication = (
                    f"Égalité multiple ({len(teams)} équipes à {pts} {unit_pts}) : mini-championnat en cours "
                    f"({len(h2h_matches)}/{expected_pairs} confrontations directes jouées). "
                    f"Départage provisoire s'appuyant sur les rencontres directes disponibles et la différence générale."
                )
            else:
                explication = (
                    f"Égalité multiple ({len(teams)} équipes à {pts} {unit_pts}) : aucune confrontation directe "
                    f"jouée à ce jour entre ces équipes. Départage provisoire à la différence de points générale "
                    f"puis au quotient général."
                )

        tiebreak_groups.append(
            {
                "points": pts,
                "nombre_equipes": len(teams),
                "equipes": [
                    {
                        "position": t.get("position"),
                        "nom": t.get("equipe") or t.get("nom"),
                        "points": t.get("points"),
                        "difference": t.get("difference"),
                        "quotient": t.get("quotient"),
                        "gagnes": t.get("gagnes"),
                        "perdus": t.get("perdus"),
                    }
                    for t in teams
                ],
                "confrontations_directes": h2h_matches,
                "statut": status,
                "explication": explication,
            }
        )

    return tiebreak_groups


async def explain_tiebreak_rules_service(
    poule_id: int | str | None = None,
    season: str = "2026-2027",
) -> dict[str, Any]:
    """Fournit les règles de départage officielles FFBB (Article 28 du RSG) et le guide d'application."""
    engine = get_regulations_engine()
    art28 = engine.get_article(
        document_id="rsg_ffbb_2026_2027",
        article_number="Article 28",
        season=season,
    )

    base_summary = (
        "En cas d'égalité de points au classement FFBB :\n"
        "1. Égalité entre 2 équipes : départage au point-average particulier (confrontations directes), "
        "puis différence de points particulière, puis quotient particulier, puis point-average général.\n"
        "2. Égalité entre 3 équipes ou plus : mini-championnat entre les équipes concernées uniquement. "
        "Classement aux points, puis différence de points particulière du mini-championnat."
    )

    res: dict[str, Any] = {
        "season": season,
        "regulation_source": "RSG FFBB (Article 28)",
        "summary": base_summary,
        "full_text": art28.content if art28 else "Article 28 non chargé.",
        "poule_id": poule_id,
    }

    if poule_id is not None:
        try:
            from .poule import ffbb_get_classement_service, get_poule_service

            poule_data = await get_poule_service(poule_id)
            classements = await ffbb_get_classement_service(poule_id)
            applied = _analyze_poule_tiebreaks(poule_data, classements)
            raw_nom = (
                poule_data.get("nom")
                or poule_data.get("libelle")
                or f"Poule {poule_id}"
            )
            poule_label = (
                raw_nom
                if str(raw_nom).lower().startswith("poule")
                else f"Poule {raw_nom}"
            )

            res["poule"] = {
                "id": poule_id,
                "nom": poule_label,
                "competition": poule_data.get("competition")
                or poule_data.get("nom_competition"),
            }
            res["applied_tiebreaks"] = applied

            if applied:
                count_ties = len(applied)
                applied_text = "\n\n".join(f"- {g['explication']}" for g in applied)
                res["summary"] = (
                    f"Application des règles de départage (Article 28) à la {poule_label} :\n"
                    f"{count_ties} situation(s) d'égalité de points détectée(s) au classement actuel :\n\n"
                    f"{applied_text}\n\n"
                    f"--- Rappel des règles générales ---\n{base_summary}"
                )
                res["presentation"] = {
                    "short_answer": (
                        f"{poule_label} : {count_ties} égalité(s) de points analysée(s). "
                        f"Départage provisoire appliqué selon les confrontations directes et la différence générale."
                    ),
                    "detail_line": f"{count_ties} groupe(s) d'équipes à égalité",
                }
            else:
                res["summary"] = (
                    f"Application des règles à la {poule_label} : aucune égalité de points constatée "
                    f"au classement actuel. Toutes les équipes ont un total de points distinct.\n\n"
                    f"--- Rappel des règles générales en cas d'égalité ---\n{base_summary}"
                )
                res["presentation"] = {
                    "short_answer": f"{poule_label} : aucune égalité de points actuellement.",
                    "detail_line": "Classement sans ex æquo",
                }
        except Exception as exc:
            logger.warning(
                "Impossible de calculer le départage pour la poule %s: %s",
                poule_id,
                exc,
            )
            res["poule"] = {
                "id": poule_id,
                "warning": f"Données de poule non disponibles ({exc})",
            }
            res["applied_tiebreaks"] = []
            res["summary"] = (
                f"Poule {poule_id} (données non disponibles : {exc}).\n\n"
                f"Rappel des règles officielles de départage (Article 28 du RSG) :\n{base_summary}"
            )
            res["presentation"] = {
                "short_answer": f"Poule {poule_id} : données non disponibles, règles officielles de l'Article 28 fournies.",
                "detail_line": "Règles générales FFBB",
            }

    return res


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
