"""Module de calcul de la dynamique, forme récente et séries en cours."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .models import FormeRecente, MatchForme, SerieEnCours
from .services.common import _normalize_name

_PARIS_TZ = ZoneInfo("Europe/Paris")


def _parse_dt_safe(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    with contextlib.suppress(ValueError, TypeError):
        dt_clean = dt_str.replace("Z", "+00:00")
        try:
            # ⚡ Bolt: Fast-path. datetime.fromisoformat() natively supports space separators
            # and formats like YYYY-MM-DD in Python 3.11+. It is significantly faster than strptime.
            dt = datetime.fromisoformat(dt_clean)
            if "T" not in dt_clean:
                # Maintain original behavior: string without 'T' truncate time and add TZ
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_PARIS_TZ)
            return dt
        except ValueError:
            # Fallback for non-standard formats or single-digit months/days (e.g., "2023-1-1")
            if len(dt_clean) >= 10:
                return datetime.strptime(dt_clean[:10], "%Y-%m-%d").replace(
                    tzinfo=_PARIS_TZ
                )
    return None


def compute_team_dynamique(
    rencontres: list[dict[str, Any]],
    eng_ids: set[str] | None = None,
    club_nom: str | None = None,
    limit: int = 5,
    ratio_global_victoires: float | None = None,
) -> dict[str, Any]:
    """Calcule la dynamique, forme récente et séries en cours d'une équipe.

    Args:
        rencontres: Liste des rencontres (poules, phases).
        eng_ids: Ensemble des IDs d'engagement de l'équipe.
        club_nom: Nom du club pour fallback de matching.
        limit: Nombre de matchs pour la forme récente (défaut: 5).
        ratio_global_victoires: Ratio global de la saison pour la tendance.

    Returns:
        Dictionnaire conforme au modèle FormeRecente.
    """
    if not rencontres:
        return FormeRecente().model_dump()

    eng_ids_set = {str(eid) for eid in (eng_ids or set()) if eid}
    club_norm = _normalize_name(club_nom or "")

    played_matches: list[dict[str, Any]] = []

    for r in rencontres:
        if not isinstance(r, dict):
            continue
        if r.get("joue") not in (1, "1", True):
            continue

        eq1 = str(r.get("nomEquipe1", "") or "")
        eq2 = str(r.get("nomEquipe2", "") or "")
        score1 = r.get("resultatEquipe1")
        score2 = r.get("resultatEquipe2")

        if score1 is None or score2 is None:
            continue
        if str(score1) in ("None", "") or str(score2) in ("None", ""):
            continue

        try:
            s1, s2 = int(str(score1)), int(str(score2))
        except ValueError, TypeError:
            continue

        # Déterminer quel côté est notre équipe
        eng1 = r.get("idEngagementEquipe1") or {}
        eng2 = r.get("idEngagementEquipe2") or {}
        eng1_id = str(eng1.get("id", "")) if isinstance(eng1, dict) else str(eng1 or "")
        eng2_id = str(eng2.get("id", "")) if isinstance(eng2, dict) else str(eng2 or "")

        our_side = None
        if eng1_id and eng1_id in eng_ids_set:
            our_side = 1
        elif eng2_id and eng2_id in eng_ids_set:
            our_side = 2
        else:
            eq1_norm = _normalize_name(eq1)
            eq2_norm = _normalize_name(eq2)
            if club_norm and club_norm in eq1_norm:
                our_side = 1
            elif club_norm and club_norm in eq2_norm:
                our_side = 2

        if our_side is None:
            continue

        our_score = s1 if our_side == 1 else s2
        their_score = s2 if our_side == 1 else s1
        adversaire = eq2 if our_side == 1 else eq1
        domicile = our_side == 1

        if our_score > their_score:
            res_char = "V"
        elif our_score < their_score:
            res_char = "D"
        else:
            res_char = "N"

        ecart = our_score - their_score
        date_str = str(r.get("date_rencontre") or r.get("date") or "")
        dt_val = _parse_dt_safe(date_str) or datetime.min.replace(tzinfo=_PARIS_TZ)

        salle_name = str(
            r.get("nomSalle")
            or r.get("nom_salle")
            or (r.get("salle_details") or {}).get("libelle")
            or ""
        )
        journee = str(r.get("nomJournee") or r.get("numJournee") or "")

        played_matches.append(
            {
                "dt": dt_val,
                "date": date_str,
                "adversaire": adversaire,
                "resultat": res_char,
                "score": f"{our_score} - {their_score}",
                "score_pour": our_score,
                "score_contre": their_score,
                "ecart": ecart,
                "domicile": domicile,
                "salle": salle_name or None,
                "journee": journee or None,
            }
        )

    if not played_matches:
        return FormeRecente().model_dump()

    # Déduplication par date + adversaire + score
    seen = set()
    deduped_matches = []
    for m in played_matches:
        key = (m["date"], m["adversaire"], m["score"])
        if key not in seen:
            seen.add(key)
            deduped_matches.append(m)

    # Tri chronologique (du plus ancien au plus récent)
    deduped_matches.sort(key=lambda x: x["dt"])

    # Calcul des séries en cours
    def _compute_streak(
        matches: list[dict[str, Any]], context_name: str = ""
    ) -> SerieEnCours:
        if not matches:
            return SerieEnCours(type="aucune", count=0, label="Aucun match joué")
        last_res = matches[-1]["resultat"]
        count = 0
        for m in reversed(matches):
            if m["resultat"] == last_res:
                count += 1
            else:
                break

        type_map = {"V": "victoires", "D": "defaites", "N": "nuls"}
        st_type = type_map.get(last_res, "inconnue")
        ctx_suffix = f" {context_name}" if context_name else ""

        if count <= 0:
            return SerieEnCours(type="aucune", count=0, label="")

        if count == 1:
            if last_res == "V":
                label = f"1 victoire{ctx_suffix}"
            elif last_res == "D":
                label = f"1 défaite{ctx_suffix}"
            else:
                label = f"1 match nul{ctx_suffix}"
            return SerieEnCours(type=st_type, count=1, label=label)

        # count >= 2 : véritable série consécutive
        if last_res == "V":
            if context_name == "à domicile":
                label = f"Invaincu à domicile ({count} victoires)"
            else:
                label = f"{count} victoires consécutives{ctx_suffix}"
        elif last_res == "D":
            label = f"{count} défaites consécutives{ctx_suffix}"
        else:
            label = f"{count} matchs nuls consécutifs{ctx_suffix}"

        return SerieEnCours(type=st_type, count=count, label=label)

    serie_actuelle = _compute_streak(deduped_matches)
    matches_dom = [m for m in deduped_matches if m["domicile"]]
    serie_domicile = _compute_streak(matches_dom, "à domicile")
    matches_ext = [m for m in deduped_matches if not m["domicile"]]
    serie_exterieur = _compute_streak(matches_ext, "à l'extérieur")

    # Forme sur les N derniers matchs
    recent = deduped_matches[-limit:]
    forme_list = [m["resultat"] for m in recent]
    forme_str = "-".join(forme_list)

    victoires_5 = sum(1 for m in recent if m["resultat"] == "V")
    defaites_5 = sum(1 for m in recent if m["resultat"] == "D")
    nuls_5 = sum(1 for m in recent if m["resultat"] == "N")
    ratio_5 = round(victoires_5 / len(recent) * 100, 1) if recent else 0.0

    pts_marques_moy = (
        round(sum(m["score_pour"] for m in recent) / len(recent), 1) if recent else 0.0
    )
    pts_encaisses_moy = (
        round(sum(m["score_contre"] for m in recent) / len(recent), 1)
        if recent
        else 0.0
    )
    diff_moy = round(pts_marques_moy - pts_encaisses_moy, 1)

    # Meilleure victoire et pire défaite sur les récents
    victoires_recent = [m for m in recent if m["resultat"] == "V"]
    defaites_recent = [m for m in recent if m["resultat"] == "D"]

    meilleure_victoire = None
    if victoires_recent:
        best_v = max(victoires_recent, key=lambda x: x["ecart"])
        meilleure_victoire = (
            f"+{best_v['ecart']} pts vs {best_v['adversaire']} ({best_v['score']})"
        )

    pire_defaite = None
    if defaites_recent:
        worst_d = min(defaites_recent, key=lambda x: x["ecart"])
        pire_defaite = (
            f"{worst_d['ecart']} pts vs {worst_d['adversaire']} ({worst_d['score']})"
        )

    # Tendance
    if ratio_global_victoires is not None:
        if ratio_5 >= ratio_global_victoires + 15:
            tendance = "En nette hausse ↗️"
        elif ratio_5 <= ratio_global_victoires - 15:
            tendance = "En baisse ↘️"
        else:
            tendance = "Stable ➡️"
    elif ratio_5 >= 60.0:
        tendance = "En hausse ↗️"
    elif ratio_5 <= 40.0:
        tendance = "En baisse ↘️"
    else:
        tendance = "Stable ➡️"

    # Matchs sérialisables
    matchs_models = [
        MatchForme(
            date=m["date"],
            adversaire=m["adversaire"],
            resultat=m["resultat"],
            score=m["score"],
            score_pour=m["score_pour"],
            score_contre=m["score_contre"],
            ecart=m["ecart"],
            domicile=m["domicile"],
            salle=m["salle"],
            journee=m["journee"],
        )
        for m in recent
    ]

    res = FormeRecente(
        forme=forme_list,
        forme_str=forme_str,
        matchs=matchs_models,
        serie_actuelle=serie_actuelle,
        serie_domicile=serie_domicile,
        serie_exterieur=serie_exterieur,
        victoires_5_derniers=victoires_5,
        defaites_5_derniers=defaites_5,
        nuls_5_derniers=nuls_5,
        ratio_victoires_5_derniers=ratio_5,
        pts_marques_moyenne_5=pts_marques_moy,
        pts_encaisses_moyenne_5=pts_encaisses_moy,
        diff_moyenne_5=diff_moy,
        meilleure_victoire=meilleure_victoire,
        pire_defaite=pire_defaite,
        tendance=tendance,
    )
    return res.model_dump()
