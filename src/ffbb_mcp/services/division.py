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
