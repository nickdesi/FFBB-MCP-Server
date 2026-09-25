"""Module de résolution d'adversaire au sein d'une poule FFBB.

Extrait de services/poule.py pour isoler l'algorithme déterministe
de matching d'équipe (Étape 3 ID-first).
"""

from __future__ import annotations

import re
from typing import Any

from ffbb_mcp.utils import (
    jaro_winkler_similarity,
    resolve_relation_field,
)

from .common import (
    _clean_team_for_match,
    _normalize_name,
)


def resolve_opponent_from_poule(
    poule_data: dict[str, Any],
    opponent_name: str,
) -> dict[str, Any]:
    """Résout l'adversaire d'un match (Étape 3 ID-first) à partir des équipes de sa poule.

    Recherche déterministe dans les classements (ou rencontres) de la poule déjà chargée.
    Retourne l'engagement_id et l'organisme_id réels de l'adversaire sans nouvelle recherche externe.
    Si la confiance est inférieure à 0.8, renvoie un statut ambigu sans décision arbitraire.
    """
    if not poule_data or not opponent_name:
        return {
            "status": "not_found",
            "resolved_id": None,
            "engagement_id": None,
            "organisme_id": None,
            "nom": None,
            "numero_equipe": None,
            "confidence": 0.0,
            "match_strategy": [],
            "ambiguous_candidates": [],
            "message": "Données de poule ou nom d'adversaire manquant.",
        }

    classements = poule_data.get("classements") or []
    # Fallback si classements vides : reconstruire les équipes depuis les rencontres
    if not classements and poule_data.get("rencontres"):
        seen_noms = set()
        virtual_classements = []
        for r in poule_data.get("rencontres", []):
            for side in ("1", "2"):
                nom = r.get(f"nomEquipe{side}")
                eng_id = r.get(f"idEngagementEquipe{side}")
                org_id = (
                    r.get(f"idOrganismeEquipe{side}")
                    or r.get(f"id_organisme_{side}")
                    or r.get(f"idOrganisme{side}")
                )
                if nom and nom not in seen_noms:
                    seen_noms.add(nom)
                    virtual_classements.append(
                        {
                            "id_engagement": {"id": eng_id, "nom": nom},
                            "organisme_nom": nom,
                            "organisme_id": str(org_id) if org_id is not None else None,
                        }
                    )
        classements = virtual_classements

    if not classements:
        return {
            "status": "not_found",
            "resolved_id": None,
            "engagement_id": None,
            "organisme_id": None,
            "nom": None,
            "numero_equipe": None,
            "confidence": 0.0,
            "match_strategy": [],
            "ambiguous_candidates": [],
            "message": "Poule sans équipes répertoriées dans les classements ou rencontres.",
        }

    raw_opp = str(opponent_name).strip()
    norm_opp = _normalize_name(raw_opp)
    clean_opp = _clean_team_for_match(raw_opp)

    # Détection d'un numéro d'équipe à la fin (1 à 9 uniquement pour ne pas confondre avec un département ex: 42, 38)
    num_match = re.search(r"[-_\s]+([1-9])$", raw_opp)
    target_num = num_match.group(1) if num_match else None
    base_raw_opp = (
        re.sub(r"[-_\s]+([1-9])$", "", raw_opp).strip() if target_num else raw_opp
    )
    base_clean_opp = _clean_team_for_match(base_raw_opp)

    candidates: list[dict[str, Any]] = []

    for c in classements:
        c_eng, c_eng_id = resolve_relation_field(c, "id_engagement")
        c_org_id = (
            str(c.get("organisme_id") or "")
            if c.get("organisme_id") is not None
            else None
        )
        c_nom = str(c_eng.get("nom") or c.get("organisme_nom") or "")
        c_num = str(c_eng.get("numero_equipe") or c_eng.get("numero_equ") or "").strip()
        c_norm = _normalize_name(c_nom)
        c_clean = _clean_team_for_match(c_nom)

        # 1. Correspondance exacte brute
        if c_nom.upper() == raw_opp.upper():
            return {
                "status": "resolved",
                "resolved_id": c_eng_id,
                "engagement_id": c_eng_id,
                "organisme_id": c_org_id,
                "nom": c_nom,
                "numero_equipe": c_num or None,
                "confidence": 1.0,
                "match_strategy": ["poule_classement_exact"],
                "ambiguous_candidates": [],
            }

        # Vérification de cohérence du numéro d'équipe
        num_consistent = True
        if (target_num and c_num and target_num != c_num) or (
            target_num and not c_num and target_num != "1"
        ):
            num_consistent = False

        if not num_consistent:
            continue

        # 2. Correspondance normalisée complète
        if c_norm == norm_opp or (c_num and f"{c_norm} {c_num}" == norm_opp):
            return {
                "status": "resolved",
                "resolved_id": c_eng_id,
                "engagement_id": c_eng_id,
                "organisme_id": c_org_id,
                "nom": c_nom,
                "numero_equipe": c_num or None,
                "confidence": 1.0,
                "match_strategy": ["poule_classement_normalized_exact"],
                "ambiguous_candidates": [],
            }

        # 3. Correspondance nettoyée (préfixes CTC / IE retirés)
        if c_clean == clean_opp or (c_num and f"{c_clean} {c_num}" == clean_opp):
            candidates.append(
                {
                    "engagement_id": c_eng_id,
                    "organisme_id": c_org_id,
                    "nom": c_nom,
                    "numero_equipe": c_num or None,
                    "score": 0.98,
                    "strategy": "poule_classement_cleaned_exact",
                }
            )
            continue

        # 4. Correspondance de base sans numéro
        if c_clean == base_clean_opp or (
            c_num and f"{c_clean} {c_num}" == base_clean_opp
        ):
            candidates.append(
                {
                    "engagement_id": c_eng_id,
                    "organisme_id": c_org_id,
                    "nom": c_nom,
                    "numero_equipe": c_num or None,
                    "score": 0.95,
                    "strategy": "poule_classement_base_exact",
                }
            )
            continue

        # 5. Inclusion sous-chaîne
        if base_clean_opp in c_clean or c_clean in base_clean_opp:
            ratio = min(len(base_clean_opp), len(c_clean)) / max(
                len(base_clean_opp), len(c_clean)
            )
            score = 0.85 + (0.10 * ratio)
            candidates.append(
                {
                    "engagement_id": c_eng_id,
                    "organisme_id": c_org_id,
                    "nom": c_nom,
                    "numero_equipe": c_num or None,
                    "score": round(score, 3),
                    "strategy": "poule_classement_inclusion",
                }
            )
            continue

        # 6. Approximatif Jaro-Winkler
        jw = jaro_winkler_similarity(c_clean, clean_opp)
        if jw >= 0.75:
            candidates.append(
                {
                    "engagement_id": c_eng_id,
                    "organisme_id": c_org_id,
                    "nom": c_nom,
                    "numero_equipe": c_num or None,
                    "score": round(jw, 3),
                    "strategy": "poule_classement_fuzzy",
                }
            )

    if not candidates:
        return {
            "status": "not_found",
            "resolved_id": None,
            "engagement_id": None,
            "organisme_id": None,
            "nom": None,
            "numero_equipe": None,
            "confidence": 0.0,
            "match_strategy": [],
            "ambiguous_candidates": [],
            "message": f"Aucun adversaire correspondant à '{opponent_name}' dans la poule.",
        }

    # Tri par score décroissant
    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[0]

    # Vérification d'ambiguïté si plusieurs candidats proches (< 0.10)
    if len(candidates) > 1:
        second = candidates[1]
        if (best["score"] - second["score"]) < 0.10:
            return {
                "status": "ambiguous",
                "resolved_id": None,
                "engagement_id": None,
                "organisme_id": None,
                "nom": None,
                "numero_equipe": None,
                "confidence": best["score"],
                "match_strategy": ["poule_ambiguous"],
                "ambiguous_candidates": candidates[:3],
                "message": (
                    f"Ambiguïté dans la poule entre plusieurs équipes pour '{opponent_name}'. "
                    "Confirmation utilisateur requise."
                ),
            }

    # Garde-fou seuil 0.8 : suspension si confiance insuffisante
    if best["score"] < 0.80:
        return {
            "status": "ambiguous",
            "resolved_id": None,
            "engagement_id": None,
            "organisme_id": None,
            "nom": None,
            "numero_equipe": None,
            "confidence": best["score"],
            "match_strategy": ["poule_low_confidence"],
            "ambiguous_candidates": [best],
            "message": (
                f"Confiance insuffisante ({best['score']}) pour '{opponent_name}'. "
                "Confirmation requise."
            ),
        }

    return {
        "status": "resolved",
        "resolved_id": best["engagement_id"],
        "engagement_id": best["engagement_id"],
        "organisme_id": best["organisme_id"],
        "nom": best["nom"],
        "numero_equipe": best["numero_equipe"],
        "confidence": best["score"],
        "match_strategy": [best["strategy"]],
        "ambiguous_candidates": [],
    }
