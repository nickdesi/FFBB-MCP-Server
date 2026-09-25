"""Module de présentation et provenance lisible pour le serveur FFBB MCP.

Garantit un rendu conversationnel clair, naturel et traçable :
- `data`: payload métier utile (équipe, match, lieu, date/heure Europe/Paris, journée fiable)
- `presentation`: textes prêts pour l'assistant (short_answer, detail_line, source_label, warnings)
- `provenance`: provenance lisible (provider='FFBB', retrieved_at, data_freshness, display_to_user=False)
  avec sous-bloc `technical` réservé aux logs et au diagnostic.

Éradique toute exposition de pseudo-citations ([connector:index]) et d'identifiants techniques.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

_PARIS_TZ = ZoneInfo("Europe/Paris")

FRENCH_DAYS = [
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
]

FRENCH_MONTHS = [
    "",
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


class MatchRoundInfo(BaseModel):
    """Informations de journée avec contrôle de fiabilité sportive."""

    display_value: int | None = Field(
        default=None,
        description="Numéro de journée exploitable pour l'affichage, ou None si non fiable.",
    )
    is_reliable: bool = Field(
        default=True,
        description="True si la numérotation est séquentielle et cohérente.",
    )
    raw_value: Any = Field(
        default=None,
        description="Valeur brute originale reçue de l'amont.",
    )
    warning: str | None = Field(
        default=None,
        description="Avertissement en cas d'anomalie de numérotation.",
    )


class VenueInfo(BaseModel):
    """Lieu et salle de la rencontre."""

    name: str | None = Field(default=None, description="Nom du gymnase ou de la salle.")
    city: str | None = Field(default=None, description="Commune ou ville.")
    address: str | None = Field(
        default=None, description="Adresse postale si disponible."
    )


class PresentationInfo(BaseModel):
    """Bloc destiné à assister la formulation naturelle par l'assistant conversationnel."""

    short_answer: str = Field(
        description="Synthèse directe et concise de l'information principale.",
    )
    detail_line: str = Field(
        description="Détails contextuels (lieu, date/heure, statut ou compétition).",
    )
    source_label: str = Field(
        description="Mention lisible de provenance et date de consultation.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Avertissements éventuels sur la qualité ou l'incohérence des données.",
    )


class ProvenanceTechnical(BaseModel):
    """Métadonnées techniques de traçabilité, strictement réservées aux logs et diagnostics."""

    connector_source_id: str = Field(
        default="ffbb_mcp",
        description="Identifiant technique du serveur/connecteur.",
    )
    cache_status: Literal["hit", "miss", "stale"] = Field(
        default="miss",
        description="État du cache interne.",
    )
    resource_ids: dict[str, Any] = Field(
        default_factory=dict,
        description="Identifiants techniques (competition_id, poule_id, engagement_id, match_id).",
    )
    raw_journee: Any = Field(
        default=None,
        description="Valeur brute de journée issue de l'amont.",
    )
    candidate_ids: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Identifiants techniques des candidats en cas de désambiguïsation.",
    )


class ProvenanceInfo(BaseModel):
    """Provenance lisible et traçabilité pour l'utilisateur et le système."""

    provider: str = Field(
        default="FFBB",
        description="Fournisseur officiel des données.",
    )
    retrieved_at: str = Field(
        default_factory=lambda: datetime.now(_PARIS_TZ).isoformat(),
        description="Horodatage ISO-8601 de récupération dans le fuseau Europe/Paris.",
    )
    data_freshness: Literal["live", "recent_cache", "stale"] = Field(
        default="live",
        description="Niveau de fraîcheur de la donnée.",
    )
    display_to_user: bool = Field(
        default=False,
        description="Flag explicite indiquant que ce bloc technique n'est pas destiné à être affiché brut.",
    )
    technical: ProvenanceTechnical = Field(
        default_factory=ProvenanceTechnical,
        description="Détails techniques réservés au diagnostic.",
    )


def evaluate_round_reliability(
    raw_round: Any,
    context_rounds: list[Any] | None = None,
) -> MatchRoundInfo:
    """Évalue la fiabilité sportive d'un numéro de journée.

    Règles de détection d'anomalie :
    - Valeur nulle, vide ou 0 -> non renseignée (display_value=None, is_reliable=False)
    - Valeur non entière ou négative -> non exploitable (display_value=None, is_reliable=False)
    - Valeur > 38 (hors championnat régulier standard) -> non fiable (display_value=None, is_reliable=False)
    - Séquence non séquentielle dans un échantillon de poule (ex: 9, 17, 35, 48) -> non séquentielle.
    """
    if raw_round is None:
        return MatchRoundInfo(display_value=None, is_reliable=False, raw_value=None)

    raw_str = str(raw_round).strip().lower()
    if raw_str in ("", "0", "none", "null"):
        return MatchRoundInfo(
            display_value=None,
            is_reliable=False,
            raw_value=raw_round,
            warning="Journée non renseignée par la source officielle.",
        )

    try:
        val = int(raw_str)
    except (ValueError, TypeError):
        return MatchRoundInfo(
            display_value=None,
            is_reliable=False,
            raw_value=raw_round,
            warning=f"Format de journée non reconnu : '{raw_round}'.",
        )

    if val < 1 or val > 38:
        return MatchRoundInfo(
            display_value=None,
            is_reliable=False,
            raw_value=raw_round,
            warning=f"Numérotation de journée aberrante ou inhabituelle ({val}).",
        )

    # Vérification d'une séquence de journées erratique dans la poule (ex: 9, 17, 35, 48)
    if context_rounds and len(context_rounds) >= 3:
        parsed_ctx: list[int] = []
        for r in context_rounds:
            try:
                parsed_ctx.append(int(str(r).strip()))
            except (ValueError, TypeError):
                continue

        if len(parsed_ctx) >= 3:
            differences = [
                parsed_ctx[i + 1] - parsed_ctx[i] for i in range(len(parsed_ctx) - 1)
            ]
            has_large_jumps = any(d > 7 or d < -7 for d in differences)
            if (
                has_large_jumps
                and val > 15
                and 1 not in parsed_ctx
                and 2 not in parsed_ctx
            ):
                return MatchRoundInfo(
                    display_value=None,
                    is_reliable=False,
                    raw_value=raw_round,
                    warning=f"Numérotation de journée non séquentielle détectée dans la compétition ({val}).",
                )

    return MatchRoundInfo(
        display_value=val,
        is_reliable=True,
        raw_value=raw_round,
        warning=None,
    )


def format_source_label(retrieved_at: datetime | None = None) -> str:
    """Génère la mention humaine de provenance et fraîcheur.

    Exemple : 'Données FFBB consultées le 20 septembre 2026 à 13:18.'
    """
    dt = retrieved_at or datetime.now(_PARIS_TZ)
    month_name = FRENCH_MONTHS[dt.month] if 1 <= dt.month <= 12 else str(dt.month)
    return f"Données FFBB consultées le {dt.day} {month_name} {dt.year} à {dt.hour:02d}:{dt.minute:02d}."


def format_french_match_datetime(
    dt_obj: datetime | None,
    time_confirmed: bool = True,
    raw_date_str: str | None = None,
) -> tuple[str | None, str | None, str]:
    """Formate une date/heure de match pour l'affichage naturel en français.

    Retourne : (date_iso_yyyy_mm_dd, time_hh_mm_ou_None, texte_lisible)
    Exemple : ('2026-09-19', '20:00', 'vendredi 19 septembre à 20 h')
    """
    if dt_obj is None:
        if raw_date_str:
            return raw_date_str[:10], None, f"le {raw_date_str[:10]}"
        return None, None, "date à confirmer"

    date_iso = dt_obj.strftime("%Y-%m-%d")
    day_name = FRENCH_DAYS[dt_obj.weekday()]
    month_name = FRENCH_MONTHS[dt_obj.month]

    if not time_confirmed or (dt_obj.hour == 0 and dt_obj.minute == 0):
        time_iso = None
        human_text = f"{day_name} {dt_obj.day} {month_name} (horaire à fixer)"
    else:
        time_iso = f"{dt_obj.hour:02d}:{dt_obj.minute:02d}"
        if dt_obj.minute == 0:
            time_text = f"{dt_obj.hour} h"
        else:
            time_text = f"{dt_obj.hour} h {dt_obj.minute:02d}"
        human_text = f"{day_name} {dt_obj.day} {month_name} à {time_text}"

    return date_iso, time_iso, human_text


def _clean_team_display_name(name: str | None) -> str:
    """Nettoie les noms d'équipes verbeux ou ALL-CAPS pour un rendu naturel."""
    if not name:
        return "Équipe"
    s = str(name).strip()
    if s.isupper() and len(s) > 3:
        words = s.split()
        capitalized = []
        for w in words:
            if w in ("US", "AS", "AL", "BC", "BB", "CS", "SCBA", "CTC", "JS"):
                capitalized.append(w)
            elif w in ("SUR", "DE", "DU", "DES", "EN", "ET", "SOUS", "D'"):
                capitalized.append(w.lower())
            else:
                capitalized.append(w.capitalize())
        return " ".join(capitalized)
    return s


def build_match_presentation(
    *,
    team_name: str,
    opponent_name: str,
    is_home: bool | None,
    status: str,
    dt_obj: datetime | None,
    time_confirmed: bool,
    home_score: int | None = None,
    away_score: int | None = None,
    venue_name: str | None = None,
    venue_city: str | None = None,
    competition_name: str | None = None,
    round_info: MatchRoundInfo | None = None,
    is_last_result: bool = True,
    warnings: list[str] | None = None,
) -> PresentationInfo:
    """Génère les phrases courtes et détaillées pour l'assistant conversationnel."""
    all_warnings = list(warnings or [])
    if round_info and round_info.warning:
        all_warnings.append(round_info.warning)

    clean_team = _clean_team_display_name(team_name)
    clean_opp = _clean_team_display_name(opponent_name)

    _date_iso, _time_iso, human_dt = format_french_match_datetime(
        dt_obj, time_confirmed
    )

    venue_parts = []
    if venue_name:
        v = venue_name.strip()
        if not v.lower().startswith("au ") and not v.lower().startswith("à "):
            venue_parts.append(f"au {v}")
        else:
            venue_parts.append(v)
    if venue_city:
        c = venue_city.strip()
        if not venue_name or c.lower() not in (venue_name or "").lower():
            venue_parts.append(f"à {c}")
    venue_suffix = f", {', '.join(venue_parts)}" if venue_parts else ""

    round_suffix = ""
    if round_info and round_info.is_reliable and round_info.display_value:
        r_val = round_info.display_value
        r_str = "1re" if r_val == 1 else f"{r_val}e"
        if competition_name:
            round_suffix = f" (C'était la {r_str} journée de {competition_name})"
        else:
            round_suffix = f" ({r_str} journée)"

    if is_last_result:
        team_score = home_score if is_home else away_score
        opp_score = away_score if is_home else home_score

        if team_score is not None and opp_score is not None:
            # Convention FFBB : score toujours domicile puis extérieur,
            # quel que soit le camp de l'équipe cible.
            if team_score > opp_score:
                short = f"{clean_team} a battu {clean_opp} {home_score} à {away_score}."
                outcome = "Victoire"
            elif team_score < opp_score:
                short = f"{clean_team} s'est incliné face à {clean_opp} {home_score} à {away_score}."
                outcome = "Défaite"
            else:
                short = f"Match nul entre {clean_team} et {clean_opp} {home_score} à {away_score}."
                outcome = "Match nul"
        else:
            short = f"Rencontre terminée entre {clean_team} et {clean_opp}."
            outcome = "Match terminé"

        loc_str = (
            "à domicile "
            if is_home is True
            else ("à l'extérieur " if is_home is False else "")
        )
        detail = f"{outcome} {loc_str}{human_dt}{venue_suffix}.{round_suffix}".strip()

    else:
        if is_home is True:
            short = f"{clean_team} recevra {clean_opp}."
            prog = f"Match à domicile programmé {human_dt}{venue_suffix}."
        elif is_home is False:
            short = f"{clean_team} se déplacera chez {clean_opp}."
            prog = f"Match à l'extérieur programmé {human_dt}{venue_suffix}."
        else:
            short = f"Le prochain match opposera {clean_team} à {clean_opp}."
            prog = f"Rencontre programmée {human_dt}{venue_suffix}."

        if round_info and round_info.is_reliable and round_info.display_value:
            r_val = round_info.display_value
            r_str = "1re" if r_val == 1 else f"{r_val}e"
            if competition_name:
                detail = f"{prog} ({r_str} journée de {competition_name})."
            else:
                detail = f"{prog} ({r_str} journée)."
        else:
            detail = prog

    return PresentationInfo(
        short_answer=short,
        detail_line=detail,
        source_label=format_source_label(),
        warnings=all_warnings,
    )


def build_provenance_block(
    *,
    source: str = "ffbb_api_live",
    cache_status: Literal["hit", "miss", "stale"] = "miss",
    resource_ids: dict[str, Any] | None = None,
    raw_journee: Any = None,
    candidate_ids: list[dict[str, Any]] | None = None,
    data_freshness: Literal["live", "recent_cache", "stale"] | None = None,
) -> dict[str, Any]:
    """Construit le bloc de provenance conforme aux exigences de masquage."""
    now_paris = datetime.now(_PARIS_TZ).isoformat()
    clean_res_ids = {
        str(k): str(v)
        for k, v in (resource_ids or {}).items()
        if v is not None and v != ""
    }

    freshness = data_freshness or ("recent_cache" if cache_status == "hit" else "live")

    tech_payload: dict[str, Any] = {
        "connector_source_id": "ffbb_mcp",
        "cache_status": cache_status,
        "resource_ids": clean_res_ids,
    }
    if raw_journee is not None:
        tech_payload["raw_journee"] = raw_journee
    if candidate_ids:
        tech_payload["candidate_ids"] = candidate_ids

    return {
        "provider": "FFBB",
        "retrieved_at": now_paris,
        "data_freshness": freshness,
        "display_to_user": False,
        "technical": tech_payload,
    }


def build_ambiguous_presentation(
    candidates: list[dict[str, Any]],
    club_name: str | None = None,
    categorie: str | None = None,
) -> dict[str, Any]:
    """Construit un bloc de présentation pour désambiguïser des équipes sans exposer d'IDs techniques."""
    user_choices: list[str] = []
    technical_candidate_ids: list[dict[str, Any]] = []

    for idx, c in enumerate(candidates, 1):
        team_label = (
            c.get("team_label")
            or c.get("nom")
            or c.get("nom_equipe")
            or categorie
            or "Équipe"
        )
        num = c.get("numero_equipe")
        comp = c.get("competition") or c.get("competition_name") or ""
        niveau = c.get("niveau") or ""

        parts = []
        if num and num not in (1, "1") and str(num) not in team_label:
            parts.append(f"{team_label} {num}")
        else:
            parts.append(team_label)

        if comp:
            parts.append(comp)
        elif niveau:
            parts.append(str(niveau))

        choice_label = " — ".join(parts)
        user_choices.append(f"{idx}. {choice_label}")

        tech_cand: dict[str, Any] = {"choice_index": idx, "label": choice_label}
        for id_key in (
            "engagement_id",
            "poule_id",
            "competition_id",
            "idOrganisme",
            "id",
        ):
            if c.get(id_key):
                tech_cand[id_key] = str(c[id_key])
        technical_candidate_ids.append(tech_cand)

    club_label = f" pour {club_name}" if club_name else ""
    cat_label = f" ({categorie})" if categorie else ""

    short_answer = (
        f"Plusieurs équipes correspondent à votre recherche{club_label}{cat_label}. "
        "Veuillez préciser votre choix parmi la liste ci-dessous."
    )
    detail_line = "\n".join(user_choices)

    presentation = PresentationInfo(
        short_answer=short_answer,
        detail_line=detail_line,
        source_label=format_source_label(),
        warnings=["Plusieurs engagements ou équipes trouvés pour cette recherche."],
    )

    provenance = build_provenance_block(
        source="ffbb_api_live",
        candidate_ids=technical_candidate_ids,
    )

    return {
        "status": "ambiguous",
        "presentation": presentation.model_dump(),
        "provenance": provenance,
        "user_choices": user_choices,
        "clarification_prompt": (
            f"Plusieurs équipes existent{club_label} : "
            + " ; ".join(user_choices)
            + ". Précisez la division, la catégorie ou le numéro d'équipe souhaité."
        ),
    }
