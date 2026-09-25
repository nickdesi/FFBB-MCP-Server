"""Helpers de parsing/resolution de divisions fédérales (NM3, PNM, R2...).

Extrait de :mod:`ffbb_mcp.services.club` pour réduire la complexité
cyclomatique du module monolithe historique (~2826 lignes).

Ce module ne dépend que de :mod:`ffbb_mcp.services.common` et des
utils purs — aucune dépendance circulaire vers ``club`` / ``poule``.
"""

from __future__ import annotations

import re
from typing import Any

from .common import _normalize_name

_DIV_PATTERN = re.compile(
    r"^(P[NR]|[NRD])([MF]?)(\d*)$"
    r"|^(P[NR]|[NRD])(\d+)([MF]?)$"
)


def _parse_division_code(raw: str | None) -> tuple[str, str | None, str] | None:
    """Parse un code de division type NM3, N3M, R2, PNM, PRM, DF2.

    Retourne (niveau, sexe, division_num) ou None si pas un code de division.
    Exemples:
      'NM3' -> ('N', 'M', '3')
      'N3M' -> ('N', 'M', '3')
      'N3'  -> ('N', None, '3')
      'R2'  -> ('R', None, '2')
      'RM2' -> ('R', 'M', '2')
      'PNM' -> ('PN', 'M', '')
      'PRM' -> ('PR', 'M', '')
      'DF2' -> ('D', 'F', '2')
    """
    if not raw:
        return None
    s = _normalize_name(raw).replace(" ", "").replace("-", "").upper()
    m = _DIV_PATTERN.match(s)
    if not m:
        return None
    if m.group(1) is not None:
        lvl = m.group(1)
        sexe = m.group(2) or None
        num = m.group(3) or ""
    else:
        lvl = m.group(4)
        num = m.group(5) or ""
        sexe = m.group(6) or None
    return (lvl, sexe, num)


def _filter_teams_by_competition(
    all_teams: list[dict[str, Any]], filtre: str
) -> list[dict[str, Any]]:
    """Filtre les équipes d'un club par niveau/division de compétition (NM3, PNM, R2, etc.).

    Vérifie le code de compétition (ex: 'NM3'), la division normalisée et le libellé.
    Exclut automatiquement les rencontres amicales si un championnat officiel existe.
    """
    if not filtre or not all_teams:
        return []

    f_norm = _normalize_name(filtre).upper()
    f_div = _parse_division_code(f_norm)
    matched: list[dict[str, Any]] = []

    for t in all_teams:
        comp_code = (t.get("competition_code") or "").strip().upper()
        comp_nom = _normalize_name(t.get("competition") or "").upper()
        comp_orig = _normalize_name(t.get("competition_origine_nom") or "").upper()
        t_sexe = (t.get("sexe") or "").strip().upper()
        t_code_norm = (
            _normalize_name(comp_code).replace(" ", "").replace("-", "").upper()
        )

        is_match = False
        # 1. Match direct ou sous-chaîne sur le code compétition
        if t_code_norm != "" and (
            f_norm == t_code_norm or (len(f_norm) >= 4 and f_norm in t_code_norm)
        ):
            is_match = True
        # 2. Match via décomposition de division
        elif f_div is not None:
            f_lvl, f_sexe, f_num = f_div
            t_div = _parse_division_code(comp_code)
            if t_div is not None:
                t_lvl, t_sexe_code, t_num = t_div
                effective_t_sexe = t_sexe_code or t_sexe
                if (
                    f_lvl == t_lvl
                    and f_num == t_num
                    and (
                        not f_sexe or not effective_t_sexe or f_sexe == effective_t_sexe
                    )
                ):
                    is_match = True
            # Match textuel si le code de la compétition n'est pas abrégé
            if not is_match:
                lvl_match = (
                    (
                        f_lvl == "N"
                        and "NATIONALE" in comp_nom
                        and "PRE NATIONALE" not in comp_nom
                    )
                    or (
                        f_lvl == "PN"
                        and ("PRE NATIONALE" in comp_nom or "PRE-NATIONALE" in comp_nom)
                    )
                    or (
                        f_lvl == "PR"
                        and ("PRE REGIONALE" in comp_nom or "PRE-REGIONALE" in comp_nom)
                    )
                    or (
                        f_lvl == "R"
                        and "REGIONALE" in comp_nom
                        and "PRE REGIONALE" not in comp_nom
                    )
                    or (f_lvl == "D" and "DEPARTEMENTALE" in comp_nom)
                )

                if lvl_match:
                    num_match = (not f_num) or (
                        f" {f_num}" in comp_nom
                        or f"DIVISION {f_num}" in comp_nom
                        or f"- {f_num}" in comp_nom
                    )
                    sexe_match = (
                        (not f_sexe)
                        or (f_sexe == t_sexe)
                        or (f_sexe == "M" and "MASCULIN" in comp_nom)
                        or (f_sexe == "F" and "FEMININ" in comp_nom)
                    )
                    if num_match and sexe_match:
                        is_match = True

        # 3. Match textuel direct sur le nom de compétition ou le code
        if (
            not is_match
            and len(f_norm) >= 3
            and (f_norm in comp_nom or f_norm in comp_orig or f_norm in t_code_norm)
        ):
            is_match = True

        if is_match:
            matched.append(t)

    if not matched:
        return []

    # Filtrer uniquement les compétitions explicitement amicales si d'autres existent
    officials = [
        t
        for t in matched
        if "AMICAL" not in _normalize_name(t.get("competition") or "").upper()
        and "AMICAL" not in _normalize_name(t.get("competition_code") or "").upper()
    ]
    return officials if officials else matched


def get_competition_level_rank(candidate: dict[str, Any]) -> int:
    """Calcule le rang hiérarchique d'un niveau de compétition.

    Plus le score est élevé, plus le niveau sportif est haut :
    - National (Championnat de France / NM / NF / Elite / organisateur F) : 3000+
    - Régional (PLAT / Brassage / RM / RF / R1-R3 / PNM / organisateur L) : 2000+
    - Départemental (DIV / DM / DF / D1-D4 / D10 / organisateur C) : 1000+

    Permet d'attribuer déterministement le rôle d'équipe fanion (équipe 1)
    à l'engagement de plus haut niveau quand ``numero_equipe`` est absent (None ou "").
    """
    comp_code = (candidate.get("competition_code") or "").strip().upper()
    comp_nom = _normalize_name(candidate.get("competition") or "").upper()
    comp_type = (candidate.get("competition_type") or "").strip().upper()
    niveau_raw = candidate.get("niveau")
    organisateur = (candidate.get("organisateur") or "").strip().upper()

    score = 0

    # 1. Détection National (3000+)
    is_national = (
        organisateur in ("F", "FEDERATION", "NATIONAL")
        or "CHAMPIONNAT DE FRANCE" in comp_nom
        or (
            "NATIONALE" in comp_nom
            and "PRE NATIONALE" not in comp_nom
            and "PRE-NATIONALE" not in comp_nom
        )
        or bool(re.match(r"^N[MF]?\d+", comp_code))
        or comp_code.startswith("NAT")
        or comp_code.startswith("ELITE")
    )
    if is_national:
        score = 3000
        if "ELITE" in comp_code or "ELITE" in comp_nom:
            score += 500
        elif "NM1" in comp_code or "NF1" in comp_code or "N1" in comp_code:
            score += 300
        elif "NM2" in comp_code or "NF2" in comp_code or "N2" in comp_code:
            score += 200
        elif "NM3" in comp_code or "NF3" in comp_code or "N3" in comp_code:
            score += 100
        return score

    # 2. Détection Régional (2000+)
    is_pre_nationale = (
        "PRE NATIONALE" in comp_nom
        or "PRE-NATIONALE" in comp_nom
        or comp_code.startswith("PN")
    )
    is_regional = (
        is_pre_nationale
        or organisateur in ("L", "LIGUE", "REGIONAL")
        or "REGIONALE" in comp_nom
        or "REGIONAL" in comp_nom
        or "BRASSAGE" in comp_nom
        or comp_type == "PLAT"
        or bool(re.match(r"^R[MF]?U?\d*", comp_code))
        or (isinstance(niveau_raw, str) and "REGIONAL" in niveau_raw.upper())
    )
    if is_regional:
        score = 2000
        if is_pre_nationale:
            score += 400
        elif "BRASSAGE" in comp_nom or "BRASSAGE" in comp_code:
            score += 300
        elif "R1" in comp_code or "R1" in comp_nom or "DIVISION 1" in comp_nom:
            score += 250
        elif "R2" in comp_code or "R2" in comp_nom or "DIVISION 2" in comp_nom:
            score += 150
        elif "R3" in comp_code or "R3" in comp_nom or "DIVISION 3" in comp_nom:
            score += 50
        elif comp_type == "PLAT":
            score += 100
        return score

    # 3. Détection Départemental (1000+)
    is_pre_regionale = (
        "PRE REGIONALE" in comp_nom
        or "PRE-REGIONALE" in comp_nom
        or comp_code.startswith("PR")
    )
    is_departemental = (
        is_pre_regionale
        or organisateur in ("C", "COMITE", "DEPARTEMENTAL")
        or "DEPARTEMENTALE" in comp_nom
        or "DEPARTEMENTAL" in comp_nom
        or comp_type == "DIV"
        or bool(re.match(r"^D[MF]?U?\d*", comp_code))
        or (isinstance(niveau_raw, str) and "DEPARTEMENTAL" in niveau_raw.upper())
    )
    if is_departemental:
        score = 1000
        if is_pre_regionale:
            score += 400
        elif "D1" in comp_code or "DIVISION 1" in comp_nom:
            score += 300
        elif "D2" in comp_code or "DIVISION 2" in comp_nom:
            score += 200
        elif "D3" in comp_code or "DIVISION 3" in comp_nom:
            score += 100
        elif "DIVISION 10" in comp_nom or "-10" in comp_code:
            score += 10  # Division basse
        return score

    # 4. Fallback générique
    if comp_type == "COUPE" or "COUPE" in comp_nom:
        return 500
    return 100


def rank_candidates_by_division(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Trie les candidats par rang hiérarchique de division (décroissant : National > Régional > Départemental).

    Déduplique strictement les phases successives d'une même équipe (même nom,
    même numéro, même base de compétition) pour éviter qu'une phase 2
    n'usurpe le rang d'une équipe réserve. Deux divisions distinctes
    (bases différentes, ex: RMU15 Brassage vs Départementale) ne sont JAMAIS
    fusionnées ici : c'est `resolve_team_by_division_rank` qui les ordonne.
    """
    if len(candidates) <= 1:
        return list(candidates)

    try:
        from .common import _normalize_name
        from .search import (
            _extract_base_competition_name,
            _is_coupe_competition,
            _phase_sort_key,
        )

        groups: dict[tuple[str, bool, str, str], list[dict[str, Any]]] = {}
        for c in candidates:
            team_name = _normalize_name(
                str(c.get("nom_equipe") or c.get("nom") or c.get("team_label") or "")
            )
            comp_name = str(c.get("competition") or c.get("competition_code") or "")
            is_coupe = _is_coupe_competition(comp_name, c.get("competition_type"))
            base_comp = _extract_base_competition_name(comp_name)
            numero = str(c.get("numero_equipe") or "").strip()
            groups.setdefault((team_name, is_coupe, base_comp, numero), []).append(c)

        cleaned: list[dict[str, Any]] = []
        for group in groups.values():
            if len(group) == 1:
                cleaned.append(group[0])
            else:
                cleaned.append(max(group, key=_phase_sort_key))
    except Exception:
        cleaned = candidates

    def _sort_key(c: dict[str, Any]) -> tuple[int, int]:
        rank = get_competition_level_rank(c)
        comp_nom = str(c.get("competition") or c.get("competition_code") or "").upper()
        comp_type = str(c.get("competition_type") or "").upper()
        is_coupe = 0 if ("COUPE" in comp_nom or comp_type == "COUPE") else 1
        return (rank, is_coupe)

    return sorted(cleaned, key=_sort_key, reverse=True)


def resolve_team_by_division_rank(
    candidates: list[dict[str, Any]],
    team_number: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Résout une équipe par son rang dans la hiérarchie des divisions quand aucun numéro explicite n'existe.

    team_number: 1 pour équipe fanion, 2 pour 1ère réserve, 3 pour 2ème réserve, etc.

    Retourne:
      - (selected_candidate, []) si le rang identifie sans ambiguïté l'équipe demandée.
      - (None, tied_candidates) si plusieurs équipes sont à égalité sur ce niveau de division (ambiguïté réelle).
      - (None, []) si le numéro demandé dépasse le nombre d'équipes disponibles (not found).
    """
    if team_number < 1:
        return None, []

    ranked = rank_candidates_by_division(candidates)
    target_idx = team_number - 1
    if target_idx < 0 or target_idx >= len(ranked):
        return None, []

    cand_at_idx = ranked[target_idx]
    cand_rank = get_competition_level_rank(cand_at_idx)

    # Vérifier l'absence d'égalité bloquante avec les équipes adjacentes
    prev_ok = (target_idx == 0) or (
        get_competition_level_rank(ranked[target_idx - 1]) > cand_rank
    )
    next_ok = (target_idx == len(ranked) - 1) or (
        cand_rank > get_competition_level_rank(ranked[target_idx + 1])
    )

    if prev_ok and next_ok:
        return cand_at_idx, []

    tied = [c for c in ranked if get_competition_level_rank(c) == cand_rank]
    return None, tied
