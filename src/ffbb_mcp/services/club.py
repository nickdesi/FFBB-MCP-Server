"""Services orientés "club" / "équipe" pour le serveur FFBB MCP.

Ce module est intentionnellement monolithique : un découpage en sous-modules
a été évalué et écarté (mauvais ratio bénéfice/risque, dépendances croisées
internes, couplage fort autour des helpers `_resolve_team_equipes` /
`_fetch_poule_matches`).

Trois sections logiques cohabitent :

1. Résolution d'équipe (≈ L43 → L318)
   ``_dedup_equipes_by_engagement``, ``ffbb_equipes_club_service``,
   ``_match_team_name``, ``_resolve_team_equipes`` : retrouvent un club puis
   filtrent ses équipes par catégorie / numéro d'équipe.

2. Bilan (``ffbb_saison_bilan_service`` ≈ L602, ``ffbb_bilan_service`` ≈ L708 → L895)
   Agrégation des statistiques (victoires, paniers, etc.) par phase et par
   équipe via les classements de poules.

3. Match & Calendrier (``ffbb_next_match_service`` ≈ L398, ``_fetch_poule_matches`` ≈ L321,
   ``get_calendrier_club_service`` ≈ L898, ``ffbb_last_result_service`` ≈ L1165)
   Récupération et formatage des rencontres (prochain match, dernier
   résultat, calendrier complet) avec enrichissement salle/adresse.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from ffbb_mcp._state import state
from ffbb_mcp.models import BilanResponse, CalendrierMatch


async def get_client_async(*args, **kwargs):
    import ffbb_mcp.client

    return await ffbb_mcp.client.get_client_async(*args, **kwargs)


import contextlib

from ffbb_mcp.utils import ParsedCategorie, format_team_name, parse_categorie

from .common import (
    _BILAN_STAT_FIELDS,
    _NUMERIC_EXTRACT_PATTERN,
    _PARIS_TZ,
    _coerce_numeric_id,
    _dedupe_inflight,
    _detect_phase_type,
    _extract_and_accumulate_bilan,
    _freshness_meta,
    _new_bilan_totals,
    _normalize_name,
    _parse_dt,
)
from .salle import _enrich_matches_with_salle_details

logger = logging.getLogger("ffbb-mcp")
_EMPTY_SET = frozenset()


def _get_max_calendar_matches() -> int:
    import ffbb_mcp.services

    return getattr(ffbb_mcp.services, "_MAX_CALENDAR_MATCHES", 300)


def _dedup_equipes_by_engagement(equipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped_equipes: list[dict[str, Any]] = []
    seen_engagement_ids: set[str] = set()
    for equipe in equipes:
        if not isinstance(equipe, dict):
            continue
        engagement_id = equipe.get("engagement_id")
        if engagement_id is None:
            deduped_equipes.append(equipe)
            continue
        engagement_key = str(engagement_id)
        if engagement_key in seen_engagement_ids:
            continue
        seen_engagement_ids.add(engagement_key)
        deduped_equipes.append(equipe)
    return deduped_equipes


def _engagement_numero(eng: Any) -> Any:
    """Extrait le numéro d'équipe d'un engagement (dict ou valeur brute)."""
    return eng.get("numeroEquipe") if isinstance(eng, dict) else None


def _compute_bilan_from_rencontres(
    poule_data: dict[str, Any],
    eng_ids: set[str],
    club_nom: str,
) -> dict[str, int] | None:
    """Calcule le bilan d'une équipe depuis les rencontres quand les classements sont vides.

    Utilisé pour les phases finales (demi-finales, finales) où le serveur FFBB
    ne fournit pas de classement mais les résultats de matchs sont disponibles.
    Retourne None si aucun match joué n'est trouvé pour l'équipe.
    """
    rencontres = poule_data.get("rencontres", []) or []
    if not rencontres:
        return None

    stats = _new_bilan_totals()
    club_norm = _normalize_name(club_nom)
    found = False

    for r in rencontres:
        if r.get("joue") not in (1, "1"):
            continue

        eq1 = r.get("nomEquipe1", "")
        eq2 = r.get("nomEquipe2", "")
        score1 = r.get("resultatEquipe1")
        score2 = r.get("resultatEquipe2")

        if score1 is None or score2 is None:
            continue

        try:
            s1, s2 = int(score1), int(score2)
        except TypeError, ValueError:
            continue

        # Déterminer quel côté est notre équipe
        eng1 = r.get("idEngagementEquipe1") or {}
        eng2 = r.get("idEngagementEquipe2") or {}
        eng1_id = str(eng1.get("id", "")) if isinstance(eng1, dict) else ""
        eng2_id = str(eng2.get("id", "")) if isinstance(eng2, dict) else ""

        our_side = None
        if eng1_id and eng1_id in eng_ids:
            our_side = 1
        elif eng2_id and eng2_id in eng_ids:
            our_side = 2
        else:
            # Fallback: matching par nom
            eq1_norm = _normalize_name(eq1)
            eq2_norm = _normalize_name(eq2)
            if club_norm and club_norm in eq1_norm:
                our_side = 1
            elif club_norm and club_norm in eq2_norm:
                our_side = 2

        if our_side is None:
            continue

        found = True
        our_score = s1 if our_side == 1 else s2
        their_score = s2 if our_side == 1 else s1

        stats["match_joues"] += 1
        stats["paniers_marques"] += our_score
        stats["paniers_encaisses"] += their_score
        if our_score > their_score:
            stats["gagnes"] += 1
        elif our_score < their_score:
            stats["perdus"] += 1
        else:
            stats["nuls"] += 1

    return stats if found else None


async def ffbb_equipes_club_service(
    organisme_id: int | str | None = None,
    filtre: str | None = None,
    org_data: dict | None = None,
) -> list[dict[str, Any]]:
    from .poule import get_organisme_service

    if org_data is not None:
        data: dict[str, Any] | None = org_data
    elif organisme_id is not None:
        data = await get_organisme_service(organisme_id)
    else:
        return []
    if not data:
        return []

    # Cache de réutilisation inter-outils (bilan/calendrier/next/last/resolve
    # pour un même club+catégorie). Évite de reconstruire les team_info et de
    # re-interroger l'organisme à chaque appel de la session.
    _eq_key = (
        f"equipes:{organisme_id}:{_normalize_name(filtre or '')}"
        if organisme_id is not None
        else None
    )
    if _eq_key is not None:
        _cached_equipes = state.cache_equipes.get(_eq_key)
        if _cached_equipes is not None:
            return copy.deepcopy(_cached_equipes)

    raw = data.get("engagements", []) if isinstance(data, dict) else []
    all_teams: list[dict[str, Any]] = []
    club_nom = data.get("nom", "")

    parsed_filter: ParsedCategorie | None = parse_categorie(filtre) if filtre else None

    for e in raw:
        if not isinstance(e, dict):
            continue
        comp = e.get("idCompetition", {}) or {}
        poule = e.get("idPoule", {}) or {}
        cat = comp.get("categorie", {}) or {}
        nom_comp = comp.get("nom", "")
        sexe_field = (comp.get("sexe") or "").upper()

        numero_equipe = e.get("numeroEquipe")
        if numero_equipe is None and nom_comp:
            parsed_comp = parse_categorie(nom_comp)
            if parsed_comp.numero_equipe:
                numero_equipe = parsed_comp.numero_equipe

        if numero_equipe is not None:
            try:
                numero_equipe = str(int(numero_equipe))
            except (TypeError, ValueError):  # fmt: skip
                numero_equipe = str(numero_equipe)

        categorie_code = cat.get("code", "") or ""
        sexe_suffix = "M" if sexe_field == "M" else "F" if sexe_field == "F" else ""

        base_cat = f"{categorie_code}{sexe_suffix}".strip()
        num_suffix = numero_equipe or ""
        cat_label = f"{base_cat}{num_suffix}" if base_cat or num_suffix else ""
        team_label = f"{club_nom} {cat_label}".strip()
        phase_label = e.get("phase") or e.get("libellePhase") or None
        team_id = e.get("id")

        team_info = {
            "team_id": team_id,
            "engagement_id": team_id,
            "numero_equipe": numero_equipe,
            "team_label": cat_label or team_label,
            "phase_label": phase_label,
            "nom_equipe": format_team_name(club_nom, num_suffix),
            "competition": nom_comp,
            "competition_id": comp.get("id"),
            "poule_id": poule.get("id"),
            "sexe": comp.get("sexe", ""),
            "categorie": categorie_code,
            "niveau": comp.get("competition_origine_niveau"),
        }
        all_teams.append(team_info)

    if parsed_filter is None:
        if _eq_key is not None:
            state.cache_equipes[_eq_key] = copy.deepcopy(all_teams)
        return all_teams

    filtered_teams: list[dict[str, Any]] = []
    for t in all_teams:
        if (
            parsed_filter.categorie
            and t["categorie"].upper() != parsed_filter.categorie.upper()
        ):
            continue
        if parsed_filter.sexe == "F" and (t["sexe"] or "").upper() == "M":
            continue
        if parsed_filter.sexe == "M" and (t["sexe"] or "").upper() == "F":
            continue
        filtered_teams.append(t)

    if parsed_filter.numero_equipe is not None:
        want_num = str(parsed_filter.numero_equipe)
        exact_matches = [
            t
            for t in filtered_teams
            if (t.get("numero_equipe") or "").strip() == want_num
        ]

        if exact_matches:
            filtered_teams = exact_matches
        else:
            empty_num_matches = [
                t for t in filtered_teams if not (t.get("numero_equipe") or "").strip()
            ]
            if empty_num_matches:
                filtered_teams = empty_num_matches
                for t in filtered_teams:
                    t["note"] = (
                        "équipe sans numéro explicite, correspond potentiellement à ce numéro"
                    )
            else:
                filtered_teams = []

    if not filtered_teams:
        suggestions = sorted(list({t["team_label"] for t in all_teams}))
        _error_result = [
            {
                "error": f"Aucune équipe matchant '{filtre}' trouvée pour '{club_nom}'.",
                "suggested_teams": suggestions,
                "hint": "Utilise l'un des labels suggérés pour une précision exacte.",
            }
        ]
        if _eq_key is not None:
            state.cache_equipes[_eq_key] = copy.deepcopy(_error_result)
        return _error_result

    if _eq_key is not None:
        state.cache_equipes[_eq_key] = copy.deepcopy(filtered_teams)
    return filtered_teams


def _match_team_name(
    nom_equipe_rencontre: str,
    organisme_nom: str,
    numero_equipe: int | None,
    is_organisme_nom_normalized: bool = False,
) -> bool:
    nom_norm = _normalize_name(nom_equipe_rencontre)
    club_norm = (
        organisme_nom if is_organisme_nom_normalized else _normalize_name(organisme_nom)
    )
    if not nom_norm or not club_norm:
        return False
    if club_norm not in nom_norm:
        return False

    search_num = numero_equipe if numero_equipe is not None else 1
    suffix = f"- {search_num}"
    suffix_norm = _normalize_name(suffix)

    if search_num == 1:
        has_digit = bool(_NUMERIC_EXTRACT_PATTERN.search(nom_norm))
        return nom_norm.endswith(suffix_norm) or not has_digit

    return nom_norm.endswith(suffix_norm)


async def _resolve_team_equipes(
    *,
    club_name: str | None,
    organisme_id: int | str | None,
    categorie: str,
    numero_equipe: int | None,
    not_found_status: str = "not_found",
) -> tuple[dict | None, list[dict], dict | None]:

    if not club_name and not organisme_id:
        return (
            {"status": "error", "message": "Fournir club_name ou organisme_id"},
            [],
            None,
        )

    import ffbb_mcp.services

    resolved_clubs, org_data = await ffbb_mcp.services.resolve_club_and_org(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
    )

    if not resolved_clubs:
        return (
            {
                "status": not_found_status,
                "message": f"Club '{club_name or organisme_id}' introuvable.",
                "club_resolu": None,
            },
            [],
            None,
        )

    if len(resolved_clubs) > 1 and not organisme_id:
        return (
            {
                "status": "ambiguous",
                "message": f"Plusieurs clubs correspondent à '{club_name}'. Précisez l'organisme_id.",
                "candidates": resolved_clubs,
                "club_resolu": None,
            },
            [],
            None,
        )

    club_resolu = resolved_clubs[0]
    target_org_id = str(club_resolu["organisme_id"])

    import ffbb_mcp.services

    equipes = await ffbb_mcp.services.ffbb_equipes_club_service(
        organisme_id=target_org_id, filtre=categorie, org_data=org_data
    )

    if not equipes or (
        isinstance(equipes, list) and len(equipes) == 1 and "error" in equipes[0]
    ):
        msg = (
            equipes[0]["error"]
            if (equipes and "error" in equipes[0])
            else f"Aucune équipe trouvée pour la catégorie '{categorie}'."
        )
        suggestions = (
            equipes[0].get("suggested_teams")
            if (equipes and "suggested_teams" in equipes[0])
            else []
        )
        return (
            {
                "status": not_found_status,
                "message": msg,
                "club_resolu": club_resolu,
                "candidates": suggestions,
            },
            [],
            club_resolu,
        )

    if numero_equipe is not None:
        want = str(numero_equipe)
        filtered = [
            e for e in equipes if (e.get("numero_equipe") or "").strip() == want
        ]
        if not filtered:
            filtered = [
                e for e in equipes if not (e.get("numero_equipe") or "").strip()
            ]
        if not filtered:
            all_available = sorted(
                list(
                    {
                        f"{e.get('team_label', categorie)} (n°{e.get('numero_equipe') or 'unique'})"
                        for e in equipes
                    }
                )
            )
            return (
                {
                    "status": not_found_status,
                    "message": f"Aucune équipe matchant '{categorie}' n°{numero_equipe} (ou unique) trouvée.",
                    "club_resolu": club_resolu,
                    "candidates": all_available,
                },
                [],
                club_resolu,
            )
        equipes = filtered

    return None, equipes, club_resolu


async def _fetch_poule_matches(
    equipes: list[dict],
    *,
    organisme_nom: str,
    numero_equipe: int | None,
    force_refresh: bool = False,
) -> list[tuple[dict, dict]]:

    numero_equipe_match = int(numero_equipe) if numero_equipe is not None else None

    async def _fetch_one(eq: dict) -> list[tuple[dict, dict]]:
        pid = eq.get("poule_id")
        my_eng = eq.get("engagement_id")
        if not pid:
            return []
        import ffbb_mcp.services

        poule = await ffbb_mcp.services.get_poule_service(
            pid, force_refresh=force_refresh
        )
        matches: list[tuple[dict, dict]] = []
        for m in poule.get("rencontres", []) or []:
            eng1 = m.get("idEngagementEquipe1")
            eng2 = m.get("idEngagementEquipe2")
            id_eng1 = str(eng1.get("id") if isinstance(eng1, dict) else eng1)
            id_eng2 = str(eng2.get("id") if isinstance(eng2, dict) else eng2)
            str_my_eng = str(my_eng) if my_eng else None

            is_my_team = False
            if str_my_eng and (str_my_eng in (id_eng1, id_eng2)):
                is_my_team = True
            else:
                organisme_nom_norm = _normalize_name(str(organisme_nom))
                is_my_team = _match_team_name(
                    str(m.get("nomEquipe1", "")),
                    organisme_nom_norm,
                    numero_equipe_match,
                    is_organisme_nom_normalized=True,
                ) or _match_team_name(
                    str(m.get("nomEquipe2", "")),
                    organisme_nom_norm,
                    numero_equipe_match,
                    is_organisme_nom_normalized=True,
                )

            if is_my_team:
                matches.append((m, eq))
        return matches

    results = await asyncio.gather(
        *[_fetch_one(e) for e in equipes if e.get("poule_id")],
        return_exceptions=True,
    )
    all_matches: list[tuple[dict, dict]] = []
    for res in results:
        if isinstance(res, list):
            all_matches.extend(res)
    return all_matches


def _prioritize_phase(
    matches_with_eq: list[tuple[dict, dict]],
) -> list[tuple[dict, dict]]:
    from .common import _extract_phase_num

    if not matches_with_eq:
        return []
    phase_to_matches: dict[int, list[tuple[dict, dict]]] = {}
    for m, eq in matches_with_eq:
        p_num = _extract_phase_num(eq.get("phase_label"))
        if p_num not in phase_to_matches:
            phase_to_matches[p_num] = []
        phase_to_matches[p_num].append((m, eq))
    max_phase = max(phase_to_matches.keys())
    return phase_to_matches[max_phase]


async def ffbb_next_match_service(
    *,
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str,
    numero_equipe: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    from .common import _extract_phase_num

    error, equipes, club_resolu = await _resolve_team_equipes(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        numero_equipe=numero_equipe,
        not_found_status="not_found",
    )
    if error:
        return error

    poules_actives = [e["poule_id"] for e in equipes if e.get("poule_id")]
    if not poules_actives:
        all_available_equipes = sorted(
            list(
                {
                    f"{e.get('team_label', categorie)} (n°{e.get('numero_equipe') or 'unique'})"
                    for e in equipes
                }
            )
        )
        return {
            "status": "not_found",
            "message": "Aucune poule active trouvée pour cette équipe.",
            "club_resolu": club_resolu,
            "candidates": all_available_equipes,
        }

    organisme_nom = str(club_resolu.get("nom", "")) if club_resolu is not None else ""

    all_matches = await _fetch_poule_matches(
        equipes,
        organisme_nom=organisme_nom,
        numero_equipe=numero_equipe,
        force_refresh=force_refresh,
    )

    tz = _PARIS_TZ
    upcoming: list[tuple[datetime, dict, dict]] = []
    for m, eq in all_matches:
        joue = m.get("joue")
        res1 = m.get("resultatEquipe1", m.get("resultat_equipe1"))
        res2 = m.get("resultatEquipe2", m.get("resultat_equipe2"))
        if joue not in (0, "0", None):
            continue
        if res1 not in (None, "", "None") or res2 not in (None, "", "None"):
            continue
        dt = _parse_dt(m.get("date_rencontre", m.get("date")))
        if dt is None:
            dt = datetime.max.replace(tzinfo=tz)
        upcoming.append((dt, m, eq))

    if not upcoming and not force_refresh:
        logger.info(
            "ffbb_next_match: aucun match trouvé en cache, "
            "tentative de rafraîchissement..."
        )
        all_matches = await _fetch_poule_matches(
            equipes,
            organisme_nom=organisme_nom,
            numero_equipe=numero_equipe,
            force_refresh=True,
        )
        upcoming = []
        for m, eq in all_matches:
            joue = m.get("joue")
            res1 = m.get("resultatEquipe1", m.get("resultat_equipe1"))
            res2 = m.get("resultatEquipe2", m.get("resultat_equipe2"))
            if joue not in (0, "0", None):
                continue
            if res1 not in (None, "", "None") or res2 not in (None, "", "None"):
                continue
            dt = _parse_dt(m.get("date_rencontre", m.get("date")))
            if dt is None:
                dt = datetime.max.replace(tzinfo=tz)
            upcoming.append((dt, m, eq))

    if not upcoming:
        all_available_equipes = sorted(
            list(
                {
                    f"{e.get('team_label', categorie)} (n°{e.get('numero_equipe') or 'unique'})"
                    for e in equipes
                }
            )
        )
        return {
            "status": "no_upcoming_match",
            "message": "Aucun match à venir trouvé pour cette équipe.",
            "club_resolu": club_resolu,
            "candidates": all_available_equipes,
        }

    phase_to_matches: dict[int, list[tuple[datetime, dict, dict]]] = {}
    for dt, m, eq in upcoming:
        p_num = _extract_phase_num(eq.get("phase_label"))
        if p_num not in phase_to_matches:
            phase_to_matches[p_num] = []
        phase_to_matches[p_num].append((dt, m, eq))

    max_active_phase = max(phase_to_matches.keys())
    active_phase_matches = phase_to_matches[max_active_phase]
    active_phase_matches.sort(key=lambda x: x[0])
    next_dt, next_match, source_team = active_phase_matches[0]

    # Fetch full rencontre details (includes salle info not available in poule data)
    match_id = next_match.get("id")
    if match_id:
        from .search import get_rencontre_service

        rencontre_detail = await get_rencontre_service(match_id)
        if rencontre_detail:
            next_match.update(rencontre_detail)

    eng1 = next_match.get("idEngagementEquipe1")
    eng2 = next_match.get("idEngagementEquipe2")
    id_eng1 = eng1.get("id") if isinstance(eng1, dict) else eng1
    id_eng2 = eng2.get("id") if isinstance(eng2, dict) else eng2
    my_eng = source_team.get("engagement_id")

    num1 = _engagement_numero(eng1)
    num2 = _engagement_numero(eng2)
    eq1_name = format_team_name(
        next_match.get("nomEquipe1", next_match.get("nom_equipe1", "")), num1
    )
    eq2_name = format_team_name(
        next_match.get("nomEquipe2", next_match.get("nom_equipe2", "")), num2
    )

    if my_eng and id_eng1 and str(my_eng) == str(id_eng1):
        adversaire = eq2_name
        domicile = True
    elif my_eng and id_eng2 and str(my_eng) == str(id_eng2):
        adversaire = eq1_name
        domicile = False
    else:
        club_nom = (source_team.get("nom_equipe") or "").lower()
        if club_nom and club_nom in (eq1_name or "").lower():
            adversaire = eq2_name
            domicile = True
        elif club_nom and club_nom in (eq2_name or "").lower():
            adversaire = eq1_name
            domicile = False
        else:
            adversaire = eq2_name or eq1_name
            domicile = None

    client = await get_client_async()
    from .salle import _enrich_with_salle_details

    await _enrich_with_salle_details(next_match, client)

    salle_details = next_match.get("salle_details") or {}
    lieu = (
        salle_details.get("libelle")
        or salle_details.get("nom")
        or next_match.get("nomSalle")
        or next_match.get("nom_salle")
        or ""
    )
    adresse_salle = (
        next_match.get("adresse_salle") or salle_details.get("adresse") or ""
    )
    ville = (
        salle_details.get("ville")
        or salle_details.get("commune")
        or next_match.get("villeSalle")
        or next_match.get("ville_salle")
        or ""
    )
    if not ville and adresse_salle:
        parts = adresse_salle.split(",")
        if len(parts) >= 2:
            ville = parts[-1].strip()

    return {
        "status": "ok",
        "club_resolu": club_resolu,
        "team": source_team,
        "match": {
            "poule_id": source_team.get("poule_id"),
            "match_id": next_match.get("id"),
            "date": next_dt.isoformat(),
            "adversaire": adversaire,
            "domicile": domicile,
            "equipe1": eq1_name,
            "equipe2": eq2_name,
            "salle": lieu,
            "ville": ville,
            "adresse": adresse_salle,
        },
        "_meta": _freshness_meta(cache="poule", force_refresh_supported=True),
    }


async def ffbb_saison_bilan_service(
    *,
    organisme_id: int | str,
    categorie: str,
    numero_equipe: int,
    force_refresh: bool = False,
) -> dict[str, Any]:
    from .poule import get_poule_service

    org_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    equipes = await ffbb_equipes_club_service(
        organisme_id=org_id_int,
        filtre=categorie,
    )
    if not equipes or (len(equipes) == 1 and "error" in equipes[0]):
        error_msg = (
            equipes[0]["error"]
            if equipes
            else f"Aucune équipe trouvée pour la catégorie '{categorie}'."
        )
        return {
            "status": "not_found",
            "message": error_msg,
            "suggestions": equipes[0].get("suggested_teams") if equipes else [],
        }

    want_num = str(numero_equipe)
    filtered_equipes = [
        e for e in equipes if (e.get("numero_equipe") or "").strip() == want_num
    ]
    if not filtered_equipes:
        filtered_equipes = [
            e for e in equipes if not (e.get("numero_equipe") or "").strip()
        ]

    if not filtered_equipes:
        return {
            "status": "not_found",
            "message": (
                "Aucune équipe ne correspond à cette combinaison "
                f"categorie={categorie!r}, numero_equipe={numero_equipe}."
            ),
        }
    equipes = filtered_equipes

    poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )
    if not poule_ids:
        return {
            "status": "not_found",
            "message": "Aucune poule associée à cette équipe.",
        }

    async def _fetch_poule(pid: str) -> dict[str, Any] | Exception:
        try:
            return await get_poule_service(pid, force_refresh=force_refresh)
        except (httpx.HTTPError, McpError, ValidationError) as e:
            return e

    poules_raw = await asyncio.gather(
        *[_fetch_poule(pid) for pid in poule_ids], return_exceptions=True
    )
    poules_map: dict[str, dict[str, Any]] = {
        pid: pd
        for pid, pd in zip(poule_ids, poules_raw, strict=False)
        if isinstance(pd, dict)
    }

    phases: list[dict[str, Any]] = []
    totaux = _new_bilan_totals()

    club_nom = equipes[0].get("nom_equipe", "")
    eng_ids = {str(e["engagement_id"]) for e in equipes if e.get("engagement_id")}

    poule_to_comp: dict[str, str] = {}
    for e in equipes:
        pid = str(e.get("poule_id", ""))
        if pid and e.get("competition"):
            poule_to_comp[pid] = e["competition"]

    for pid, poule_data in poules_map.items():
        classements = poule_data.get("classements", []) or []
        for entry in classements:
            eng = entry.get("id_engagement", {}) or {}
            entry_eng_id = str(eng.get("id", ""))
            if entry_eng_id not in eng_ids:
                continue

            stats = _extract_and_accumulate_bilan(entry, totaux)
            phases.append(
                {
                    "competition": poule_to_comp.get(pid, poule_data.get("nom", "")),
                    "poule_id": pid,
                    "position": entry.get("position"),
                    "total_equipes": len(classements),
                    "phase_type": _detect_phase_type(poule_to_comp.get(pid, "")),
                    "phase_terminee": poule_data.get("phase_terminee", False),
                    **stats,
                }
            )

        if not classements:
            stats_from_rencontres = _compute_bilan_from_rencontres(
                poule_data, eng_ids, club_nom
            )
            if stats_from_rencontres:
                for k, v in stats_from_rencontres.items():
                    totaux[k] += v
                phases.append(
                    {
                        "competition": poule_to_comp.get(
                            pid, poule_data.get("nom", "")
                        ),
                        "poule_id": pid,
                        "position": None,
                        "total_equipes": None,
                        "phase_type": _detect_phase_type(poule_to_comp.get(pid, "")),
                        "phase_terminee": poule_data.get("phase_terminee", False),
                        **stats_from_rencontres,
                    }
                )

    phases.sort(key=lambda x: x["competition"])

    saison_terminee = (
        all(p.get("phase_terminee", True) for p in phases) if phases else True
    )

    competitions_incluses = sorted(
        {p["competition"] for p in phases if p.get("competition")}
    )

    return {
        "status": "ok",
        "club": club_nom,
        "categorie": categorie or "",
        "bilan_total": totaux,
        "saison_terminee": saison_terminee,
        "competitions_incluses": competitions_incluses,
        "phases": phases,
        "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
    }


async def _build_bilan_payload(
    club_name: str | None,
    organisme_id: int | str | None,
    categorie: str | None,
) -> dict[str, Any]:
    """Calcule le payload complet d'un bilan pour un club / catégorie.

    Extrait de la closure `_fetch` historiquement définie dans
    `ffbb_bilan_service`. Pas de logique de cache ici : la mise en cache /
    déduplication est entièrement gérée par l'appelant via `_dedupe_inflight`.
    """
    from .poule import get_poule_service
    from .search import resolve_club_and_org

    resolved_clubs, org_data = await resolve_club_and_org(
        club_name=club_name, organisme_id=organisme_id, categorie=categorie
    )
    target_org_ids = [str(c["organisme_id"]) for c in resolved_clubs]
    club_nom = resolved_clubs[0]["nom"] if resolved_clubs else (club_name or "")

    if not target_org_ids:
        return {
            "error": f"Club '{club_name}' introuvable",
            "suggestion": "Vérifiez l'orthographe ou résolvez d'abord le club avec ffbb_search.",
            "next_call": f"ffbb_search(type='organismes', query='{club_name or ''}')",
            "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
        }

    eq_tasks = []
    for oid in target_org_ids:
        is_target = organisme_id and str(oid) == str(organisme_id)
        pass_org = org_data if is_target else None
        eq_tasks.append(
            ffbb_equipes_club_service(
                organisme_id=oid, filtre=categorie, org_data=pass_org
            )
        )
    eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

    equipes: list[dict[str, Any]] = []
    for res in eq_results:
        if isinstance(res, list):
            equipes.extend([e for e in res if isinstance(e, dict) and "error" not in e])
        elif isinstance(res, Exception):
            logger.error("Erreur lors de la récupération des équipes: %s", res)

    if not equipes:
        return {
            "error": f"Aucune équipe trouvée pour la catégorie '{categorie}'",
            "suggestion": "Listez les équipes disponibles puis choisissez la catégorie et le numéro exacts.",
            "next_call": (
                f"ffbb_club(action='equipes', organisme_id={target_org_ids[0]})"
                if target_org_ids
                else "ffbb_club(action='equipes', club_name='<club>')"
            ),
            "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
        }

    equipes = _dedup_equipes_by_engagement(equipes)

    unique_poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )
    logger.debug(
        f"ffbb_bilan: cible_orgs_count={len(target_org_ids)} "
        f"equipes_count={len(equipes)} unique_poules_count={len(unique_poule_ids)}"
    )

    async def _fetch_poule_bilan(pid: str) -> dict[str, Any] | Exception:
        try:
            return await get_poule_service(pid)
        except (httpx.HTTPError, McpError, ValidationError) as e:
            return e

    poules_raw = await asyncio.gather(
        *[_fetch_poule_bilan(pid) for pid in unique_poule_ids],
        return_exceptions=True,
    )
    poules_map: dict[str, dict[str, Any]] = {
        pid: pd
        for pid, pd in zip(unique_poule_ids, poules_raw, strict=False)
        if isinstance(pd, dict)
    }

    poule_to_eng: dict[str, set[str]] = {}
    poule_to_comp: dict[str, str] = {}
    eng_to_num: dict[str, str] = {}
    org_ids_str = set(target_org_ids)
    for e in equipes:
        pid = str(e.get("poule_id", ""))
        eid = str(e.get("engagement_id", ""))
        num = str(e.get("numero_equipe") or "")
        if pid and eid:
            if pid not in poule_to_eng:
                poule_to_eng[pid] = set()
            poule_to_eng[pid].add(eid)
            if num:
                eng_to_num[eid] = num
        if pid and e.get("competition"):
            poule_to_comp[pid] = e["competition"]

    phases: list[dict[str, Any]] = []
    totaux = _new_bilan_totals()

    for pid, poule_data in poules_map.items():
        if not isinstance(poule_data, dict):
            continue
        eng_ids_here = poule_to_eng.get(pid, _EMPTY_SET)
        classements = poule_data.get("classements", []) or []
        for entry in classements:
            if not isinstance(entry, dict):
                continue
            eng = entry.get("id_engagement", {}) or {}
            entry_eng_id = str(eng.get("id", ""))
            entry_org_id = str(entry.get("organisme_id", ""))

            if entry_eng_id in eng_ids_here:
                pass
            elif entry_org_id in org_ids_str:
                logger.debug("ffbb_bilan: fallback org_id utilisé")
            else:
                continue

            stats = _extract_and_accumulate_bilan(entry, totaux)

            num_equipe = eng_to_num.get(entry_eng_id) or str(
                eng.get("numero_equipe") or ""
            )

            phases.append(
                {
                    "competition": poule_to_comp.get(pid, ""),
                    "poule_id": pid,
                    "numero_equipe": num_equipe,
                    "position": entry.get("position"),
                    "total_equipes": len(classements),
                    "phase_type": poule_data.get("phase_type", "poule"),
                    "phase_terminee": poule_data.get("phase_terminee", False),
                    **stats,
                }
            )

        if not classements:
            stats_from_rencontres = _compute_bilan_from_rencontres(
                poule_data, eng_ids_here, club_nom
            )
            if stats_from_rencontres:
                for k, v in stats_from_rencontres.items():
                    totaux[k] += v
                matching_nums = [
                    eng_to_num[eid] for eid in eng_ids_here if eid in eng_to_num
                ]
                num_equipe = matching_nums[0] if matching_nums else "1"
                phases.append(
                    {
                        "competition": poule_to_comp.get(pid, ""),
                        "poule_id": pid,
                        "numero_equipe": num_equipe,
                        "position": None,
                        "total_equipes": None,
                        "phase_type": _detect_phase_type(poule_to_comp.get(pid, "")),
                        "phase_terminee": poule_data.get("phase_terminee", False),
                        **stats_from_rencontres,
                    }
                )

    def _phase_sort_key_by_age(p: dict) -> tuple[int, str, int, str]:
        comp = p.get("competition") or ""
        parsed = parse_categorie(comp)

        # 1. Âge (catégorie) : plus jeune en premier (U9 < U11 < Seniors)
        age = 999
        cat = parsed.categorie
        if cat and cat.startswith("U"):
            with contextlib.suppress(ValueError):
                age = int(cat[1:])
        elif "SENIOR" in comp.upper():
            age = 100
        else:
            age = 90

        # 2. Sexe
        sexe = parsed.sexe or ""

        # 3. Numéro d'équipe
        num = p.get("numero_equipe")
        try:
            num_int = int(num) if num else 1
        except ValueError:
            num_int = 1

        return (age, sexe, num_int, comp)

    phases.sort(key=_phase_sort_key_by_age)

    equipes_bilan: dict[str, Any] = {}
    for p in phases:
        num = p["numero_equipe"] or "1"
        if num not in equipes_bilan:
            equipes_bilan[num] = {
                "numero_equipe": num,
                "bilan": _new_bilan_totals(),
                "phases": [],
            }
        equipes_bilan[num]["phases"].append(p)
        b = equipes_bilan[num]["bilan"]
        for f in _BILAN_STAT_FIELDS:
            b[f] += p[f]

    phase_courante = None
    if phases:
        target_phases = [p for p in phases if str(p.get("numero_equipe", "1")) == "1"]
        phase_courante = target_phases[-1] if target_phases else phases[-1]

    saison_terminee = (
        all(p.get("phase_terminee", True) for p in phases) if phases else True
    )

    def _comp_sort_key_by_age(comp_name: str) -> tuple[int, str]:
        parsed = parse_categorie(comp_name)
        age = 999
        cat = parsed.categorie
        if cat and cat.startswith("U"):
            with contextlib.suppress(ValueError):
                age = int(cat[1:])
        elif "SENIOR" in comp_name.upper():
            age = 100
        else:
            age = 90
        return (age, comp_name)

    competitions_incluses = sorted(
        {p["competition"] for p in phases if p.get("competition")},
        key=_comp_sort_key_by_age,
    )

    res_dict = {
        "club": club_nom,
        "categorie": categorie or "",
        "bilan_total": totaux,
        "phase_courante": phase_courante,
        "saison_terminee": saison_terminee,
        "competitions_incluses": competitions_incluses,
        "equipes_bilan": equipes_bilan,
        "phases": phases,
        "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
    }
    # Validation stricte via Pydantic
    return BilanResponse(**res_dict).model_dump(by_alias=True)  # type: ignore[arg-type]


async def ffbb_bilan_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    cache_key = f"bilan:{organisme_id or ''}:{_normalize_name(club_name or '')}:{_normalize_name(categorie or '')}"

    if force_refresh and state.cache_bilan is not None:
        logger.debug("force_refresh=True, bypass cache pour bilan")
        state.cache_bilan.pop(cache_key, None)

    return await _dedupe_inflight(
        cache=state.cache_bilan,
        cache_key=cache_key,
        inflight_map=state.inflight_bilan,
        make_coro=lambda: _build_bilan_payload(club_name, organisme_id, categorie),
        cache_name="bilan",
    )


async def _build_calendar_matches(
    club_name: str | None,
    organisme_id: int | str | None,
    categorie: str | None,
    numero_equipe: int | None,
    adversaire: str | None,
    date_debut: str | None,
    date_fin: str | None,
    limit: int | None,
) -> list[dict]:
    """Construit la liste des matchs (calendrier complet) pour un club / catégorie.

    Extrait de la closure `_fetch` historiquement définie dans
    `get_calendrier_club_service`. Pas de logique de cache ici : la mise en
    cache / déduplication est entièrement gérée par l'appelant via
    `_dedupe_inflight`.
    """
    from .search import resolve_club_and_org

    resolved_clubs, _ = await resolve_club_and_org(
        club_name=club_name, organisme_id=organisme_id, categorie=categorie, limit=5
    )

    if not resolved_clubs:
        return [
            {
                "error": f"Aucun club trouvé pour '{club_name or organisme_id}'. "
                "Vérifie l'orthographe ou utilise ffbb_search.",
            }
        ]

    if len(resolved_clubs) > 1 and not organisme_id:
        candidates = [
            {
                "id": c.get("organisme_id"),
                "nom": c.get("nom"),
                "ville": c.get("ville"),
            }
            for c in resolved_clubs
            if isinstance(c, dict)
        ]
        return [
            {
                "error": f"Plusieurs clubs correspondent à '{club_name}'. "
                "Précise l'organisme_id ou un nom plus exact.",
                "candidates": candidates,
            }
        ]

    target_org_ids = [str(c["organisme_id"]) for c in resolved_clubs]
    target_org_ids = list(dict.fromkeys(oid for oid in target_org_ids if oid))

    # Extraire le nom du club résolu pour le filtrage par adversaire
    club_nom_resolu = resolved_clubs[0].get("nom", "") if resolved_clubs else ""

    import ffbb_mcp.services

    eq_tasks = [
        ffbb_mcp.services.ffbb_equipes_club_service(organisme_id=oid, filtre=categorie)
        for oid in target_org_ids
    ]
    eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

    equipes: list[dict[str, Any]] = []
    for res in eq_results:
        if isinstance(res, list):
            equipes.extend([e for e in res if isinstance(e, dict) and "error" not in e])
        elif isinstance(res, Exception):
            logger.error("Erreur lors de la récupération des équipes: %s", res)

    if numero_equipe is not None:
        equipes = [
            e
            for e in equipes
            if str(e.get("numero_equipe", "")) == str(numero_equipe)
            or str(e.get("nom", "")).endswith(f"- {numero_equipe}")
            or f" - {numero_equipe} " in str(e.get("nom", ""))
            or f"-{numero_equipe} " in str(e.get("nom", ""))
        ]

    if not equipes:
        return [
            {
                "warning": (
                    f"Aucune équipe active pour '{club_name or organisme_id}' "
                    f"(catégorie: '{categorie or 'toutes'}'). "
                    "Le club existe mais n'a pas d'équipes engagées."
                ),
                "equipes": [],
            }
        ]

    equipes = _dedup_equipes_by_engagement(equipes)

    seen_match_ids: set[Any] = set()
    all_matches: list[dict[str, Any]] = []

    unique_poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )

    poule_tasks = [
        ffbb_mcp.services.get_poule_service(poule_id) for poule_id in unique_poule_ids
    ]
    poules_data = await asyncio.gather(*poule_tasks, return_exceptions=True)
    poules_by_id = {
        poule_id: poule_data
        for poule_id, poule_data in zip(unique_poule_ids, poules_data, strict=False)
    }

    for equipe in equipes:
        poule_id = equipe.get("poule_id")
        if not poule_id:
            continue

        poule_data = poules_by_id.get(str(poule_id))
        if (
            not isinstance(poule_data, dict)
            or not poule_data
            or "rencontres" not in poule_data
        ):
            continue

        for match in poule_data.get("rencontres", []) or []:
            if not isinstance(match, dict):
                continue
            match_id = match.get("id")
            if not match_id or match_id in seen_match_ids:
                continue

            seen_match_ids.add(match_id)

            eng1 = match.get("idEngagementEquipe1")
            eng2 = match.get("idEngagementEquipe2")
            num1 = _engagement_numero(eng1)
            num2 = _engagement_numero(eng2)

            eq1 = format_team_name(
                match.get("nomEquipe1", match.get("nom_equipe1", "")), num1
            )
            eq2 = format_team_name(
                match.get("nomEquipe2", match.get("nom_equipe2", "")), num2
            )
            score1 = match.get("resultatEquipe1", match.get("resultat_equipe1"))
            score2 = match.get("resultatEquipe2", match.get("resultat_equipe2"))
            date_match = match.get("date_rencontre", match.get("date", ""))
            journee = match.get("numeroJournee", match.get("numero_journee", ""))
            joue = match.get("joue")
            salle = match.get("salle") or match.get("idSalle") or match.get("id_salle")

            calendar_match = {
                "id": match_id,
                "date": date_match,
                "joue": joue,
                "equipe1": eq1,
                "equipe2": eq2,
                "score_equipe1": score1,
                "score_equipe2": score2,
                "competition_nom": equipe.get("competition", ""),
                "competition_type": _detect_phase_type(equipe.get("competition", "")),
                "num_journee": journee,
            }
            if salle:
                calendar_match["salle"] = salle
            all_matches.append(calendar_match)

    # Enrichissement bulk des salle_ids via list_rencontres_async par poule
    # (l'endpoint poule ne retourne pas les salle_id → 1 appel async par poule)
    _matches_need_salle = [m for m in all_matches if not m.get("salle") and m.get("id")]
    if _matches_need_salle:
        _poule_ids = list(
            dict.fromkeys(
                str(e.get("poule_id") or "") for e in equipes if e.get("poule_id")
            )
        )
        if _poule_ids:
            try:
                from .common import get_client_async as _get_client

                _client = await _get_client()

                async def _fetch_by_poule(pid: str) -> list:
                    fc = json.dumps({"idPoule": {"_eq": int(pid)}})
                    try:
                        return await _client.list_rencontres_async(
                            limit=500, filter_criteria=fc
                        )
                    except httpx.HTTPError, ValidationError:
                        return []

                _rencontres_lists = await asyncio.gather(
                    *[_fetch_by_poule(pid) for pid in _poule_ids],
                    return_exceptions=True,
                )
                _salle_map: dict[str, str] = {}
                for _res in _rencontres_lists:
                    if isinstance(_res, list):
                        for _r in _res:
                            if _r.id and _r.salle:
                                raw = _r.salle
                                sid = (
                                    str(raw.get("id", raw))
                                    if isinstance(raw, dict)
                                    else str(raw)
                                )
                                _salle_map[str(_r.id)] = sid
                for m in _matches_need_salle:
                    _sid = _salle_map.get(str(m["id"]))
                    if _sid:
                        m["salle"] = _sid
            except AttributeError, TypeError:
                pass  # Fallback silencieux (forme inattendue des rencontres)

    await _enrich_matches_with_salle_details(all_matches)

    # Extraction ville/adresse depuis salle_details vers les champs plats
    for m in all_matches:
        sd = m.get("salle_details") or {}
        if sd:
            if not m.get("ville"):
                m["ville"] = sd.get("ville") or sd.get("commune") or ""
            if not m.get("adresse"):
                m["adresse"] = (
                    m.get("adresse_salle")
                    or sd.get("adresse")
                    or sd.get("adresse1")
                    or ""
                )
            # nom_salle = libelle de la salle
            m["nom_salle"] = sd.get("libelle") or ""
            # lieu_complet = "Nom Salle - Adresse, CP Ville"
            commune = sd.get("commune") or {}
            cp = (
                sd.get("code_postal")
                or commune.get("code_postal")
                or commune.get("codePostal")
                or ""
            )
            nom = m.get("nom_salle") or ""
            adr = sd.get("adresse") or m.get("adresse_salle") or ""
            vil = m.get("ville") or ""
            cp_ville = " ".join(filter(None, [cp, vil]))
            adresse_postale = ", ".join(filter(None, [adr, cp_ville]))
            parts = [p for p in [nom, adresse_postale] if p]
            m["lieu_complet"] = " - ".join(parts)

    tz = _PARIS_TZ
    now = datetime.now(tz)

    for m in all_matches:
        m["_dt"] = _parse_dt(m.get("date"))

    # Filtrage par dates
    if date_debut:
        all_matches = [
            m
            for m in all_matches
            if m["_dt"] and m["_dt"].strftime("%Y-%m-%d") >= date_debut
        ]
    if date_fin:
        all_matches = [
            m
            for m in all_matches
            if m["_dt"] and m["_dt"].strftime("%Y-%m-%d") <= date_fin
        ]

    # Filtrage par adversaire (confrontations directes)
    if adversaire:
        adversaire_norm = _normalize_name(adversaire)
        club_norm = _normalize_name(club_nom_resolu)

        # Ne garder que les matchs où le club ET l'adversaire se rencontrent
        all_matches = [
            m
            for m in all_matches
            if (
                # Cas 1: club est equipe1, adversaire est equipe2
                (
                    club_norm in _normalize_name(m.get("equipe1", ""))
                    and adversaire_norm in _normalize_name(m.get("equipe2", ""))
                )
                # Cas 2: club est equipe2, adversaire est equipe1
                or (
                    club_norm in _normalize_name(m.get("equipe2", ""))
                    and adversaire_norm in _normalize_name(m.get("equipe1", ""))
                )
            )
        ]

    all_matches.sort(key=lambda x: (x["_dt"] is None, x["_dt"] or now), reverse=True)

    # Limitation optionnelle
    if limit is not None:
        all_matches = all_matches[:limit]

    played_indices: list[int] = []
    future_indices: list[int] = []

    for idx, m in enumerate(all_matches):
        m["played"] = (
            m.get("joue") == 1 or m.get("joue") == "1" or m.get("joue") is True
        )
        if m["played"]:
            played_indices.append(idx)
        else:
            future_indices.append(idx)

    last_played_idx = played_indices[0] if played_indices else None
    next_future_idx = future_indices[-1] if future_indices else None

    for idx, m in enumerate(all_matches):
        m["is_last_match"] = last_played_idx is not None and idx == last_played_idx
        m["is_next_match"] = next_future_idx is not None and idx == next_future_idx
        m.pop("_dt", None)

    effective = all_matches

    max_matches = _get_max_calendar_matches()
    if len(effective) > max_matches:
        truncated = effective[:max_matches]
        warning = {
            "warning": (
                "Résultat tronqué côté MCP: trop de matchs pour ce club/catégorie. "
                "Affichage limité pour protéger les performances. "
                "Affinez votre requête (catégorie précise, équipe 1/2, phase, etc.)."
            ),
            "total_initial": len(all_matches),
            "limite_appliquee": max_matches,
        }
        # Validation stricte via Pydantic
        validated_trunc = []
        for m in truncated:
            if "warning" in m:
                validated_trunc.append(m)
            else:
                validated_trunc.append(CalendrierMatch(**m).model_dump(by_alias=True))
        validated_trunc.append(warning)
        return validated_trunc

    # Validation stricte via Pydantic
    validated_matches = []
    for m in effective:
        if "warning" in m:
            validated_matches.append(m)
        else:
            validated_matches.append(CalendrierMatch(**m).model_dump(by_alias=True))
    return validated_matches


async def get_calendrier_club_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    numero_equipe: int | None = None,
    *,
    adversaire: str | None = None,
    date_debut: str | None = None,
    date_fin: str | None = None,
    limit: int | None = None,
    force_refresh: bool = False,
) -> list[dict]:
    cache_key = f"calendrier:{organisme_id or ''}:{_normalize_name(club_name or '')}:{_normalize_name(categorie or '')}:{numero_equipe or ''}:{_normalize_name(adversaire or '')}:{date_debut or ''}:{date_fin or ''}:{limit or ''}"

    if force_refresh and state.cache_calendrier is not None:
        state.cache_calendrier.pop(cache_key, None)

    return await _dedupe_inflight(
        cache=state.cache_calendrier,
        cache_key=cache_key,
        inflight_map=state.inflight_calendrier,
        make_coro=lambda: _build_calendar_matches(
            club_name,
            organisme_id,
            categorie,
            numero_equipe,
            adversaire,
            date_debut,
            date_fin,
            limit,
        ),
        cache_name="calendrier",
    )


async def ffbb_last_result_service(
    *,
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str,
    numero_equipe: int = 1,
    force_refresh: bool = False,
) -> dict:
    error, equipes, club_resolu = await _resolve_team_equipes(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        numero_equipe=numero_equipe,
        not_found_status="no_result",
    )
    if error:
        return error

    organisme_nom = str(club_resolu.get("nom", "")) if club_resolu is not None else ""

    async def _get_latest_match(
        refresh: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        all_matches = await _fetch_poule_matches(
            equipes,
            organisme_nom=organisme_nom,
            numero_equipe=numero_equipe,
            force_refresh=refresh,
        )
        joues = [
            (m, eq)
            for m, eq in all_matches
            if m.get("joue") == 1 and m.get("resultatEquipe1") not in (None, "None")
        ]
        if not joues:
            return None

        active_phase = _prioritize_phase(joues)
        active_phase.sort(
            key=lambda x: (
                _parse_dt(x[0].get("date_rencontre", "") or "")
                or datetime.min.replace(tzinfo=_PARIS_TZ)
            ),
            reverse=True,
        )
        return active_phase[0][0], active_phase[0][1]

    latest_tuple: (
        tuple[dict[str, Any], dict[str, Any]] | None
    ) = await _get_latest_match(force_refresh)
    dernier: dict[str, Any] | None = latest_tuple[0] if latest_tuple else None
    source_eq: dict[str, Any] = latest_tuple[1] if latest_tuple else {}

    if dernier and not force_refresh:
        date_str = dernier.get("date_rencontre", "")
        if len(date_str) >= 10:
            seuil_str = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            if date_str[:10] < seuil_str:
                logger.info(
                    "ffbb_last_result: match > 30 jours, force_refresh déclenché."
                )
                dernier_refresh_tuple = await _get_latest_match(True)
                if dernier_refresh_tuple:
                    dernier = dernier_refresh_tuple[0]
                    source_eq = dernier_refresh_tuple[1]

    if not dernier:
        all_available_equipes = sorted(
            list(
                {
                    f"{e.get('team_label', categorie)} (n°{e.get('numero_equipe') or 'unique'})"
                    for e in equipes
                }
            )
        )
        return {
            "status": "no_result",
            "message": "Aucun match joué trouvé.",
            "club_resolu": club_resolu,
            "candidates": all_available_equipes,
            "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
        }

    # Fetch full rencontre details (includes salle info not available in poule data)
    dernier_id = dernier.get("id")
    if dernier_id:
        from .search import get_rencontre_service

        rencontre_detail = await get_rencontre_service(dernier_id)
        if rencontre_detail:
            dernier.update(rencontre_detail)

    _numero_equipe_match = int(numero_equipe) if numero_equipe is not None else None
    est_domicile = _match_team_name(
        str(dernier.get("nomEquipe1", "")), str(organisme_nom), _numero_equipe_match
    )

    def _safe_int(val: Any) -> int | None:
        if val is None or val in ("", "None"):
            return None
        try:
            return int(val)
        except (TypeError, ValueError):  # fmt: skip
            return None

    score_nous_raw = (
        dernier["resultatEquipe1"] if est_domicile else dernier["resultatEquipe2"]
    )
    score_eux_raw = (
        dernier["resultatEquipe2"] if est_domicile else dernier["resultatEquipe1"]
    )
    score_nous = _safe_int(score_nous_raw)
    score_eux = _safe_int(score_eux_raw)
    victoire = (
        score_nous is not None and score_eux is not None and score_nous > score_eux
    )

    eng1 = dernier.get("idEngagementEquipe1")
    eng2 = dernier.get("idEngagementEquipe2")
    num1 = _engagement_numero(eng1)
    num2 = _engagement_numero(eng2)

    client = await get_client_async()
    from .salle import _enrich_with_salle_details

    await _enrich_with_salle_details(dernier, client)

    salle_details = dernier.get("salle_details") or {}
    lieu = (
        salle_details.get("libelle")
        or salle_details.get("nom")
        or dernier.get("nomSalle")
        or dernier.get("nom_salle")
        or ""
    )
    adresse_salle = dernier.get("adresse_salle") or salle_details.get("adresse") or ""
    ville = (
        salle_details.get("ville")
        or salle_details.get("commune")
        or dernier.get("villeSalle")
        or dernier.get("ville_salle")
        or ""
    )
    if not ville and adresse_salle:
        parts = adresse_salle.split(",")
        if len(parts) >= 2:
            ville = parts[-1].strip()

    competition_name = source_eq.get("competition", "")
    phase_label = source_eq.get("phase_label")

    return {
        "status": "ok",
        "club_resolu": club_resolu,
        "date": dernier.get("date_rencontre", ""),
        "journee": dernier.get("numeroJournee"),
        "competition": competition_name,
        "competition_id": source_eq.get("competition_id"),
        "phase_type": _detect_phase_type(competition_name),
        "phase_label": phase_label,
        "domicile": format_team_name(dernier.get("nomEquipe1", ""), num1),
        "score_domicile": dernier.get("resultatEquipe1"),
        "exterieur": format_team_name(dernier.get("nomEquipe2", ""), num2),
        "score_exterieur": dernier.get("resultatEquipe2"),
        "salle": lieu,
        "ville": ville,
        "adresse": adresse_salle,
        "victoire": victoire,
        "_meta": _freshness_meta(cache="poule", force_refresh_supported=True),
    }
