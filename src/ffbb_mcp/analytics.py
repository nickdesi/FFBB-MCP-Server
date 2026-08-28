"""Module d'analyse statistique avancée, benchmarking et comparaisons face-à-face (H2H)."""

from __future__ import annotations

import contextlib
from typing import Any
from zoneinfo import ZoneInfo

from .services.common import _normalize_name

_PARIS_TZ = ZoneInfo("Europe/Paris")


def compute_poule_advanced_stats(
    poule_data: dict[str, Any],
    target_eng_id: str | None = None,
    club_nom: str | None = None,
) -> dict[str, Any]:
    """Calcule le profil avancé d'une équipe au sein de sa poule.

    Statistiques calculées :
    - Rang d'attaque et de défense dans la poule
    - Moyennes de points marqués et encaissés
    - Bilans séparés Domicile et Extérieur
    - Indice Clutch (performance dans les matchs à <= 5 points d'écart)
    - Style de jeu détecté
    """
    classements = poule_data.get("classements", []) or []
    rencontres = poule_data.get("rencontres", []) or []
    total_equipes = len(classements)

    # 1. Rangs d'attaque et défense depuis le classement
    rankings_attack = []
    rankings_defense = []
    target_entry = None
    target_eng_str = str(target_eng_id) if target_eng_id else None
    club_norm = _normalize_name(club_nom or "")

    for c in classements:
        if not isinstance(c, dict):
            continue
        eng = c.get("id_engagement", {}) or {}
        eid = str(eng.get("id", "")) if isinstance(eng, dict) else str(eng or "")
        nom_eq = str(c.get("nom_equipe") or eng.get("nom", "") or "")
        mj = int(c.get("match_joues") or c.get("joues") or 0)
        pm = int(c.get("paniers_marques") or c.get("marques") or 0)
        pe = int(c.get("paniers_encaisses") or c.get("encaisses") or 0)

        avg_pm = round(pm / mj, 1) if mj > 0 else 0.0
        avg_pe = round(pe / mj, 1) if mj > 0 else 0.0

        is_target = False
        if (target_eng_str and eid == target_eng_str) or (
            club_norm and club_norm in _normalize_name(nom_eq)
        ):
            is_target = True

        entry_summary = {
            "nom": nom_eq,
            "engagement_id": eid,
            "avg_attaque": avg_pm,
            "avg_defense": avg_pe,
            "diff": pm - pe,
            "matchs_joues": mj,
            "position": c.get("position"),
        }
        if is_target:
            target_entry = entry_summary

        rankings_attack.append(entry_summary)
        rankings_defense.append(entry_summary)

    rankings_attack.sort(
        key=lambda x: float(str(x.get("avg_attaque") or 0.0)), reverse=True
    )
    rankings_defense.sort(
        key=lambda x: float(str(x.get("avg_defense") or 0.0))
    )  # Plus petit = meilleure défense

    rang_attaque = None
    rang_defense = None
    if target_entry:
        with contextlib.suppress(ValueError):
            rang_attaque = rankings_attack.index(target_entry) + 1
        with contextlib.suppress(ValueError):
            rang_defense = rankings_defense.index(target_entry) + 1

    # 2. Analyse détaillée des rencontres (Domicile / Extérieur / Clutch)
    matches_dom = {"v": 0, "d": 0, "n": 0, "pts_pour": 0, "pts_contre": 0}
    matches_ext = {"v": 0, "d": 0, "n": 0, "pts_pour": 0, "pts_contre": 0}
    clutch_matches = {"joues": 0, "v": 0, "d": 0}

    for r in rencontres:
        if not isinstance(r, dict) or r.get("joue") not in (1, "1", True):
            continue
        score1 = r.get("resultatEquipe1")
        score2 = r.get("resultatEquipe2")
        if score1 in (None, "None", "") or score2 in (None, "None", ""):
            continue
        try:
            s1, s2 = int(str(score1)), int(str(score2))
        except ValueError, TypeError:
            continue

        eng1 = r.get("idEngagementEquipe1") or {}
        eng2 = r.get("idEngagementEquipe2") or {}
        eng1_id = str(eng1.get("id", "")) if isinstance(eng1, dict) else str(eng1 or "")
        eng2_id = str(eng2.get("id", "")) if isinstance(eng2, dict) else str(eng2 or "")
        eq1 = str(r.get("nomEquipe1", "") or "")
        eq2 = str(r.get("nomEquipe2", "") or "")

        our_side = None
        if target_eng_str and target_eng_str in (eng1_id, eng2_id):
            our_side = 1 if target_eng_str == eng1_id else 2
        elif club_norm:
            if club_norm in _normalize_name(eq1):
                our_side = 1
            elif club_norm in _normalize_name(eq2):
                our_side = 2

        if our_side is None:
            continue

        our_score = s1 if our_side == 1 else s2
        their_score = s2 if our_side == 1 else s1
        is_home = our_side == 1
        diff = our_score - their_score

        target_dict = matches_dom if is_home else matches_ext
        target_dict["pts_pour"] += our_score
        target_dict["pts_contre"] += their_score
        if our_score > their_score:
            target_dict["v"] += 1
        elif our_score < their_score:
            target_dict["d"] += 1
        else:
            target_dict["n"] += 1

        # Match serré (Clutch : écart <= 5 points)
        if abs(diff) <= 5:
            clutch_matches["joues"] += 1
            if diff > 0:
                clutch_matches["v"] += 1
            elif diff < 0:
                clutch_matches["d"] += 1

    tot_dom = matches_dom["v"] + matches_dom["d"] + matches_dom["n"]
    tot_ext = matches_ext["v"] + matches_ext["d"] + matches_ext["n"]

    dom_stats = {
        "victoires": matches_dom["v"],
        "defaites": matches_dom["d"],
        "nuls": matches_dom["n"],
        "matchs_joues": tot_dom,
        "ratio_victoires": (
            round(matches_dom["v"] / tot_dom * 100, 1) if tot_dom > 0 else 0.0
        ),
        "moyenne_marques": (
            round(matches_dom["pts_pour"] / tot_dom, 1) if tot_dom > 0 else 0.0
        ),
        "moyenne_encaisses": (
            round(matches_dom["pts_contre"] / tot_dom, 1) if tot_dom > 0 else 0.0
        ),
    }

    ext_stats = {
        "victoires": matches_ext["v"],
        "defaites": matches_ext["d"],
        "nuls": matches_ext["n"],
        "matchs_joues": tot_ext,
        "ratio_victoires": (
            round(matches_ext["v"] / tot_ext * 100, 1) if tot_ext > 0 else 0.0
        ),
        "moyenne_marques": (
            round(matches_ext["pts_pour"] / tot_ext, 1) if tot_ext > 0 else 0.0
        ),
        "moyenne_encaisses": (
            round(matches_ext["pts_contre"] / tot_ext, 1) if tot_ext > 0 else 0.0
        ),
    }

    # Style de jeu
    style = "Équipe équilibrée ⚖️"
    if rang_attaque and rang_defense and total_equipes:
        if (
            rang_attaque <= max(2, total_equipes // 3)
            and rang_defense > total_equipes // 2
        ):
            style = "Attaque explosive 💥 (Portée vers l'offensive)"
        elif (
            rang_defense <= max(2, total_equipes // 3)
            and rang_attaque > total_equipes // 2
        ):
            style = "Forteresse défensive 🛡️ (Verrouille les matchs)"
        elif rang_attaque <= max(3, total_equipes // 3) and rang_defense <= max(
            3, total_equipes // 3
        ):
            style = "Complète & dominante 👑 (Top attaque et défense)"
        elif rang_attaque > total_equipes // 2 and rang_defense > total_equipes // 2:
            style = "En difficulté sur les deux côtés du terrain ⚠️"

    clutch_ratio = (
        round(clutch_matches["v"] / clutch_matches["joues"] * 100, 1)
        if clutch_matches["joues"] > 0
        else 0.0
    )

    return {
        "rang_attaque": f"{rang_attaque}/{total_equipes}" if rang_attaque else None,
        "rang_defense": f"{rang_defense}/{total_equipes}" if rang_defense else None,
        "moyenne_points_marques": target_entry.get("avg_attaque")
        if target_entry
        else None,
        "moyenne_points_encaisses": target_entry.get("avg_defense")
        if target_entry
        else None,
        "style_de_jeu": style,
        "domicile": dom_stats,
        "exterieur": ext_stats,
        "clutch_index": {
            "matchs_serres_joues": clutch_matches["joues"],
            "victoires_serrees": clutch_matches["v"],
            "defaites_serrees": clutch_matches["d"],
            "taux_reussite_clutch": clutch_ratio,
            "label": (
                f"{clutch_matches['v']}/{clutch_matches['joues']} victoires dans les matchs à <= 5 pts"
                if clutch_matches["joues"] > 0
                else "Aucun match serré disputé"
            ),
        },
    }


def compute_head_to_head(
    rencontres: list[dict[str, Any]],
    eng_id_a: str | None = None,
    nom_a: str | None = None,
    eng_id_b: str | None = None,
    nom_b: str | None = None,
) -> dict[str, Any]:
    """Analyse les confrontations directes (Face-à-Face / Head-to-Head) entre deux équipes."""
    norm_a = _normalize_name(nom_a or "")
    norm_b = _normalize_name(nom_b or "")
    eid_a = str(eng_id_a) if eng_id_a else None
    eid_b = str(eng_id_b) if eng_id_b else None

    direct_matches: list[dict[str, Any]] = []
    victoires_a = 0
    victoires_b = 0
    nuls = 0
    total_pts_a = 0
    total_pts_b = 0

    for r in rencontres:
        if not isinstance(r, dict) or r.get("joue") not in (1, "1", True):
            continue
        score1 = r.get("resultatEquipe1")
        score2 = r.get("resultatEquipe2")
        if score1 in (None, "None", "") or score2 in (None, "None", ""):
            continue
        try:
            s1, s2 = int(str(score1)), int(str(score2))
        except ValueError, TypeError:
            continue

        eq1 = str(r.get("nomEquipe1", "") or "")
        eq2 = str(r.get("nomEquipe2", "") or "")
        eng1 = r.get("idEngagementEquipe1") or {}
        eng2 = r.get("idEngagementEquipe2") or {}
        eng1_id = str(eng1.get("id", "")) if isinstance(eng1, dict) else str(eng1 or "")
        eng2_id = str(eng2.get("id", "")) if isinstance(eng2, dict) else str(eng2 or "")

        side_a = None
        side_b = None

        if eid_a and eid_a == eng1_id:
            side_a = 1
        elif eid_a and eid_a == eng2_id:
            side_a = 2
        elif norm_a and norm_a in _normalize_name(eq1):
            side_a = 1
        elif norm_a and norm_a in _normalize_name(eq2):
            side_a = 2

        if eid_b and eid_b == eng1_id:
            side_b = 1
        elif eid_b and eid_b == eng2_id:
            side_b = 2
        elif norm_b and norm_b in _normalize_name(eq1):
            side_b = 1
        elif norm_b and norm_b in _normalize_name(eq2):
            side_b = 2

        # Confrontation directe entre A et B
        if side_a is not None and side_b is not None and side_a != side_b:
            pts_a = s1 if side_a == 1 else s2
            pts_b = s2 if side_a == 1 else s1
            date_str = str(r.get("date_rencontre") or r.get("date") or "")
            salle = str(
                r.get("nomSalle")
                or r.get("nom_salle")
                or (r.get("salle_details") or {}).get("libelle")
                or ""
            )

            total_pts_a += pts_a
            total_pts_b += pts_b
            if pts_a > pts_b:
                victoires_a += 1
                vainqueur = nom_a or "Équipe A"
            elif pts_b > pts_a:
                victoires_b += 1
                vainqueur = nom_b or "Équipe B"
            else:
                nuls += 1
                vainqueur = "Nul"

            direct_matches.append(
                {
                    "date": date_str,
                    "score": f"{s1} - {s2}",
                    "equipe_domicile": eq1,
                    "equipe_exterieur": eq2,
                    "points_a": pts_a,
                    "points_b": pts_b,
                    "vainqueur": vainqueur,
                    "salle": salle or None,
                }
            )

    count = len(direct_matches)
    label_a = nom_a or "Équipe A"
    label_b = nom_b or "Équipe B"

    if count == 0:
        bilan_h2h = f"Aucune confrontation directe jouée sur la saison entre {label_a} et {label_b}."
    elif victoires_a > victoires_b:
        bilan_h2h = f"Avantage {label_a} ({victoires_a}V - {victoires_b}D)"
    elif victoires_b > victoires_a:
        bilan_h2h = f"Avantage {label_b} ({victoires_b}V - {victoires_a}D)"
    else:
        bilan_h2h = f"Égalité parfaite ({victoires_a}V - {victoires_b}D)"

    return {
        "confrontations_count": count,
        "bilan_h2h": bilan_h2h,
        "victoires_a": victoires_a,
        "victoires_b": victoires_b,
        "nuls": nuls,
        "moyenne_points_a": round(total_pts_a / count, 1) if count > 0 else 0.0,
        "moyenne_points_b": round(total_pts_b / count, 1) if count > 0 else 0.0,
        "diff_total": total_pts_a - total_pts_b,
        "matchs": direct_matches,
    }
