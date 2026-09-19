"""Référentiel officiel et résolveur strict des types de compétitions et pratiques FFBB.

Issu directement des métadonnées du schéma Directus de ffbb-api :
- `fields/ffbbserver_competitions/typeCompetition`
- `fields/ffbbserver_rencontres/pratique`

Garantit :
1. La préservation intégrale des codes bruts FFBB (ex: 'PLAT', 'DIV', 'COUPE').
2. La préservation intégrale des libellés de compétition (ex: 'RFU13 Brassage').
3. L'interdiction absolue d'inventer une traduction par inférence (ex: ne jamais forcer 'format plateau').
4. Un enrichissement uniquement si documenté officiellement par l'API.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# Table de correspondance officielle issue de l'endpoint :
# GET https://api.ffbb.app/fields/ffbbserver_competitions/typeCompetition
# Interface : select-dropdown, translations: 'Type de compétition'
OFFICIAL_COMPETITION_TYPE_CHOICES: dict[str, str] = {
    "DIV": "Championnat",
    "COUPE": "Coupe",
    "PLAT": "Plateau",
    "DIV_3X3": "Championnat 3x3",
    "DIV_3x3": "Championnat 3x3",
}

# Table de correspondance officielle issue de l'endpoint :
# GET https://api.ffbb.app/fields/ffbbserver_rencontres/pratique
# Interface : select-dropdown
OFFICIAL_PRACTICE_CHOICES: dict[str, str] = {
    "5x5": "Basket 5×5",
    "3x3": "Basket 3×3",
    "Handisport": "Handisport",
}


class CompetitionTypeDetail(BaseModel):
    """Représentation fidèle et documentée du type de compétition FFBB."""

    code: str | None = Field(
        default=None,
        description="Code technique brut fourni par ffbb-api (ex: 'PLAT', 'DIV', 'COUPE').",
    )
    label: str | None = Field(
        default=None,
        description="Libellé officiel exact issu du référentiel ffbb-api ou None si non documenté.",
    )
    source: str = Field(
        default="fields/ffbbserver_competitions/typeCompetition",
        description="Origine du mapping (endpoint ou schéma ffbb-api).",
    )
    documented: bool = Field(
        default=False,
        description="True si le code dispose d'une définition officielle vérifiée dans ffbb-api.",
    )


def resolve_competition_type(
    code: str | None,
    allow_official_mapping: bool = True,
) -> CompetitionTypeDetail:
    """Résout fidèlement le type de compétition selon le référentiel officiel Directus.

    Si allow_official_mapping=False ou si le code n'est pas dans le schéma officiel,
    aucun libellé n'est inventé et documented=False est retourné.
    """
    if not code:
        return CompetitionTypeDetail(
            code=None,
            label=None,
            source="fields/ffbbserver_competitions/typeCompetition",
            documented=False,
        )

    raw_str = str(code).strip()
    code_upper = raw_str.upper()

    if allow_official_mapping and (
        raw_str in OFFICIAL_COMPETITION_TYPE_CHOICES
        or code_upper in OFFICIAL_COMPETITION_TYPE_CHOICES
    ):
        canonical_label = (
            OFFICIAL_COMPETITION_TYPE_CHOICES.get(raw_str)
            or OFFICIAL_COMPETITION_TYPE_CHOICES[code_upper]
        )
        return CompetitionTypeDetail(
            code=raw_str,
            label=canonical_label,
            source="fields/ffbbserver_competitions/typeCompetition",
            documented=True,
        )

    return CompetitionTypeDetail(
        code=raw_str,
        label=None,
        source="ffbb-api",
        documented=False,
    )


def resolve_practice(practice_raw: Any) -> dict[str, Any]:
    """Résout la pratique (5x5, 3x3) à partir du code officiel de la rencontre."""
    if not practice_raw:
        return {"code": None, "label": None}

    if isinstance(practice_raw, dict):
        code = practice_raw.get("code") or practice_raw.get("pratique")
    else:
        code = str(practice_raw).strip()

    if not code:
        return {"code": None, "label": None}

    c_str = str(code).strip()
    label = OFFICIAL_PRACTICE_CHOICES.get(c_str, c_str)
    return {"code": c_str, "label": label}


def format_competition_display(
    competition_name: str | None,
    poule_name: str | None = None,
    practice: str | dict[str, Any] | None = None,
    competition_type_detail: CompetitionTypeDetail | dict[str, Any] | None = None,
) -> str:
    """Produit le rendu utilisateur officiel et fiable sans extrapolation.

    Exemple : 'RFU13 Brassage — Poule A — Basket 5×5'
    Ne contient JAMAIS 'format plateau' ni d'inférence non sollicitée.
    """
    parts: list[str] = []

    comp_clean = (competition_name or "").strip()
    if comp_clean:
        parts.append(comp_clean)

    poule_clean = (poule_name or "").strip()
    if poule_clean:
        parts.append(poule_clean)

    if practice:
        if isinstance(practice, dict):
            prat_label = practice.get("label") or practice.get("code")
        else:
            prat_label = OFFICIAL_PRACTICE_CHOICES.get(
                str(practice).strip(), str(practice).strip()
            )
        if prat_label:
            parts.append(prat_label)

    return " — ".join(parts) if parts else ""


def format_competition_technical_detail(
    type_detail: CompetitionTypeDetail | dict[str, Any] | None,
) -> str:
    """Formate l'explication technique si l'utilisateur demande explicitement le détail."""
    if not type_detail:
        return "Code technique FFBB : non renseigné"

    if isinstance(type_detail, CompetitionTypeDetail):
        code = type_detail.code
        label = type_detail.label
        documented = type_detail.documented
        source = type_detail.source
    else:
        code = type_detail.get("code")
        label = type_detail.get("label")
        documented = type_detail.get("documented", False)
        source = type_detail.get("source", "ffbb-api")

    if documented and label:
        return (
            f"Code technique FFBB : {code}\n"
            f"Libellé officiel associé : {label} (source: {source})"
        )

    return (
        f"Code technique FFBB : {code or 'inconnu'}\n"
        "Libellé officiel associé : non documenté dans ffbb-api"
    )
