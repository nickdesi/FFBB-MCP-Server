"""Services orientés "club" / "équipe" pour le serveur FFBB MCP.

Orchestrateur : le monolithe historique (~2826 lignes) a été découpé
depuis 1.13 :

* :mod:`ffbb_mcp.services.division` → parsing divisions (NM3, PNM...)
* :mod:`ffbb_mcp.services.bilan` → ``ffbb_bilan_service`` & ``ffbb_saison_bilan_service``
* :mod:`ffbb_mcp.services.calendar` → ``get_calendrier_club_service``

Ce module conserve la résolution d'équipe et le routage next/last/H2H,
et ré-exporte les symboles déplacés pour compatibilité
(``from ffbb_mcp.services.club import _parse_division_code`` reste valide).
"""

from __future__ import annotations

import asyncio
import copy
import logging
from datetime import datetime, timedelta
from typing import Any

from ffbb_mcp._state import state


async def get_client_async(*args, **kwargs):
    import ffbb_mcp.client

    return await ffbb_mcp.client.get_client_async(*args, **kwargs)


from ffbb_mcp.utils import ParsedCategorie, format_team_name, parse_categorie

from .bilan import (
    _build_bilan_payload,  # noqa: F401
    _compute_bilan_from_rencontres,  # noqa: F401  re-export compat
    ffbb_bilan_service,  # noqa: F401
    ffbb_saison_bilan_service,  # noqa: F401
)
from .calendar import (
    _build_calendar_matches,  # noqa: F401
    get_calendrier_club_service,  # noqa: F401
)
from .common import (
    _NUMERIC_EXTRACT_PATTERN,
    _PARIS_TZ,
    _compute_match_statut,
    _detect_phase_type,
    _freshness_meta,
    _is_horaire_renseigne,
    _normalize_name,
    _parse_dt,
)
from .division import (
    _DIV_PATTERN,  # noqa: F401
    _filter_teams_by_competition,
    _parse_division_code,
)
from .search import ffbb_resolve_team_service  # noqa: F401

logger = logging.getLogger("ffbb-mcp")
_EMPTY_SET: set[str] = set()


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


async def ffbb_equipes_club_service(
    organisme_id: int | str | None = None,
    filtre: str | None = None,
    org_data: dict | None = None,
    force_refresh: bool = False,
    season_id: int | str | None = None,
) -> list[dict[str, Any]]:
    from .poule import get_organisme_service

    if org_data is not None:
        data: dict[str, Any] | None = org_data
    elif organisme_id is not None:
        data = await get_organisme_service(organisme_id, force_refresh=force_refresh)
    else:
        return []
    if not data:
        return []

    # Cache de réutilisation inter-outils (bilan/calendrier/next/last/resolve
    # pour un même club+catégorie). Évite de reconstruire les team_info et de
    # re-interroger l'organisme à chaque appel de la session.
    _eq_key = (
        f"equipes:{organisme_id}:{_normalize_name(filtre or '')}:{season_id or ''}"
        if organisme_id is not None and org_data is None
        else None
    )
    if _eq_key is not None and not force_refresh:
        _cached_equipes = state.cache_equipes.get(_eq_key)
        if _cached_equipes is not None:
            return [t.copy() for t in _cached_equipes]

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
        comp_code = (comp.get("code") or "").strip()
        comp_type = (comp.get("typeCompetition") or "").strip()
        comp_orig = (comp.get("competition_origine_nom") or "").strip()
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
        # Normalisation IDs en string opaque (évite perte précision JS, cohérence contrat)
        team_id_str = str(team_id) if team_id is not None else None
        comp_id_raw = comp.get("id")
        poule_id_raw = poule.get("id")

        saison_raw = (
            (comp.get("saison") or {}).get("id")
            if isinstance(comp.get("saison"), dict)
            else None
        )
        team_info = {
            "team_id": team_id_str,
            "engagement_id": team_id_str,
            "numero_equipe": numero_equipe,
            "team_label": cat_label or team_label,
            "phase_label": phase_label,
            "nom_equipe": format_team_name(club_nom, num_suffix),
            "competition": nom_comp,
            "competition_code": comp_code,
            "competition_type": comp_type,
            "competition_origine_nom": comp_orig,
            "competition_id": str(comp_id_raw) if comp_id_raw is not None else None,
            "poule_id": str(poule_id_raw) if poule_id_raw is not None else None,
            "season_id": str(saison_raw) if saison_raw is not None else None,
            "sexe": comp.get("sexe", ""),
            "categorie": categorie_code,
            "niveau": comp.get("competition_origine_niveau"),
        }
        all_teams.append(team_info)

    # Filtrage saison si demandé (cohérence FFBB-API : idCompetition.saison.id)
    if season_id is not None:
        sid = str(season_id).strip()
        original_for_season = list(all_teams)
        all_teams = [
            t for t in all_teams if str(t.get("season_id") or "").strip() == sid
        ]
        if not all_teams:
            if _eq_key is not None:
                state.cache_equipes[_eq_key] = []
            return [
                {
                    "error": f"Aucune équipe pour la saison '{season_id}' trouvée pour '{club_nom}'.",
                    "suggested_teams": sorted(
                        list({t["team_label"] for t in original_for_season})
                    ),
                    "hint": "Vérifie le season_id via ffbb_saisons.",
                }
            ]

    if not filtre:
        if _eq_key is not None:
            state.cache_equipes[_eq_key] = [t.copy() for t in all_teams]
        return all_teams

    # 1) Filtrage prioritaire par catégorie standard (ex: U18M, U13F, Senior...) si applicable
    filtered_teams: list[dict[str, Any]] = []
    is_division_filter = _parse_division_code(filtre) is not None

    if parsed_filter and parsed_filter.categorie and not is_division_filter:
        for t in all_teams:
            t_cat = (t.get("categorie") or "").upper().strip()
            f_cat = parsed_filter.categorie.upper().strip()
            is_match = (t_cat == f_cat) or (
                {t_cat, f_cat} <= {"SE", "SENIOR", "SENIORS"}
            )
            if not is_match:
                continue
            if parsed_filter.sexe == "F" and (t.get("sexe") or "").upper() == "M":
                continue
            if parsed_filter.sexe == "M" and (t.get("sexe") or "").upper() == "F":
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
                    t
                    for t in filtered_teams
                    if not (t.get("numero_equipe") or "").strip()
                ]
                if empty_num_matches:
                    filtered_teams = empty_num_matches
                    for t in filtered_teams:
                        t["note"] = (
                            "équipe sans numéro explicite, correspond potentiellement à ce numéro"
                        )
                else:
                    filtered_teams = []
    else:
        # 2) Filtrage par niveau / division / code de compétition (ex: NM3, PNM, R2...)
        comp_matches = _filter_teams_by_competition(all_teams, filtre)
        if comp_matches:
            filtered_teams = comp_matches
        else:
            for t in all_teams:
                t_cat = (t.get("categorie") or "").upper().strip()
                if parsed_filter and parsed_filter.categorie:
                    f_cat = parsed_filter.categorie.upper().strip()
                    is_match = (t_cat == f_cat) or (
                        {t_cat, f_cat} <= {"SE", "SENIOR", "SENIORS"}
                    )
                    if not is_match:
                        continue
                if (
                    parsed_filter
                    and parsed_filter.sexe == "F"
                    and (t.get("sexe") or "").upper() == "M"
                ):
                    continue
                if (
                    parsed_filter
                    and parsed_filter.sexe == "M"
                    and (t.get("sexe") or "").upper() == "F"
                ):
                    continue
                filtered_teams.append(t)

        if parsed_filter and parsed_filter.numero_equipe is not None:
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
                    t
                    for t in filtered_teams
                    if not (t.get("numero_equipe") or "").strip()
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
    str_num = str(search_num)

    has_trailing_num = (
        nom_norm.endswith(f"- {str_num}")
        or nom_norm.endswith(f" {str_num}")
        or nom_norm.endswith(f"-{str_num}")
        or nom_norm.endswith(f"_{str_num}")
    )

    if search_num == 1:
        has_digit = bool(_NUMERIC_EXTRACT_PATTERN.search(nom_norm))
        return has_trailing_num or not has_digit

    return has_trailing_num


async def _resolve_team_equipes(
    *,
    club_name: str | None,
    organisme_id: int | str | None,
    categorie: str | None = None,
    numero_equipe: int | None,
    engagement_id: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    poule_id: int | str | None = None,
    season_id: int | str | None = None,
    not_found_status: str = "not_found",
    force_refresh: bool = False,
) -> tuple[dict | None, list[dict], dict | None]:

    if not club_name and not organisme_id:
        side_hint = (
            "club_a (ou club_name) / organisme_id_a"
            if "a" in not_found_status.lower()
            else "club_b (ou adversaire) / organisme_id_b"
        )
        return (
            {"status": "error", "message": f"Fournir {side_hint}"},
            [],
            None,
        )

    import ffbb_mcp.services as svc

    resolved_clubs, org_data = await svc.resolve_club_and_org(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        force_refresh=force_refresh,
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

    if len(resolved_clubs) > 1 and not organisme_id and club_name:
        norm_name = _normalize_name(club_name)
        if _normalize_name(resolved_clubs[0].get("nom", "")) == norm_name:
            second_norm = (
                _normalize_name(resolved_clubs[1].get("nom", ""))
                if len(resolved_clubs) > 1
                else ""
            )
            if second_norm != norm_name:
                resolved_clubs = [resolved_clubs[0]]

    equipes: list[dict[str, Any]] | None = None
    if len(resolved_clubs) > 1 and not organisme_id and categorie:
        matching_clubs: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for rc in resolved_clubs:
            rc_id = rc.get("organisme_id")
            if not rc_id:
                continue
            try:
                rc_teams = await svc.ffbb_equipes_club_service(
                    organisme_id=rc_id,
                    filtre=categorie,
                    force_refresh=force_refresh,
                    season_id=season_id,
                )
            except Exception:
                rc_teams = []
            if rc_teams and not (
                isinstance(rc_teams, list)
                and len(rc_teams) == 1
                and "error" in rc_teams[0]
            ):
                matching_clubs.append((rc, rc_teams))
        if len(matching_clubs) == 1:
            resolved_clubs = [matching_clubs[0][0]]
            equipes = matching_clubs[0][1]

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

    if equipes is None:
        import unittest.mock

        eq_fn = ffbb_equipes_club_service
        if isinstance(
            ffbb_equipes_club_service,
            (unittest.mock.AsyncMock, unittest.mock.MagicMock),
        ):
            eq_fn = ffbb_equipes_club_service
        elif isinstance(
            getattr(svc, "ffbb_equipes_club_service", None),
            (unittest.mock.AsyncMock, unittest.mock.MagicMock),
        ):
            eq_fn = svc.ffbb_equipes_club_service

        equipes = await eq_fn(
            organisme_id=target_org_id,
            filtre=categorie,
            org_data=org_data,
            force_refresh=force_refresh,
            season_id=season_id,
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

    # Application des filtres de désambiguïsation explicites par ordre de priorité strict
    if engagement_id is not None:
        target_eng = str(engagement_id).strip()
        equipes = [
            e
            for e in equipes
            if str(e.get("engagement_id") or e.get("team_id") or "").strip()
            == target_eng
        ]

    if poule_id is not None:
        target_poule = str(poule_id).strip()
        equipes = [
            e for e in equipes if str(e.get("poule_id") or "").strip() == target_poule
        ]

    if competition_id is not None:
        target_comp = str(competition_id).strip()
        equipes = [
            e
            for e in equipes
            if str(e.get("competition_id") or "").strip() == target_comp
        ]

    if competition_type is not None:
        target_type = str(competition_type).strip().upper()
        equipes = [
            e
            for e in equipes
            if str(e.get("competition_type") or "").strip().upper() == target_type
        ]

    if season_id is not None:
        target_season = str(season_id).strip()
        equipes = [
            e for e in equipes if str(e.get("season_id") or "").strip() == target_season
        ]

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

    if not equipes:
        return (
            {
                "status": not_found_status,
                "message": f"Aucun engagement ne correspond aux critères spécifiés pour '{categorie}'.",
                "club_resolu": club_resolu,
                "candidates": [],
            },
            [],
            club_resolu,
        )

    # Détection d'ambiguïté si plusieurs compétitions distinctes subsistent sans filtre explicite
    comp_ids = {str(e.get("competition_id") or "") for e in equipes}
    eng_ids = {str(e.get("engagement_id") or e.get("team_id") or "") for e in equipes}
    if (
        len(comp_ids) > 1
        and engagement_id is None
        and competition_id is None
        and competition_type is None
        and poule_id is None
        and season_id is None
    ):
        return (
            {
                "status": "ambiguous",
                "message": f"Plusieurs engagements ({len(equipes)}) existent pour '{categorie}'. Précisez `engagement_id`, `competition_id` ou `competition_type`.",
                "candidates": equipes,
                "club_resolu": club_resolu,
            },
            [],
            club_resolu,
        )
    # Également ambigu si plusieurs engagement_id distincts même compétition (rare mais possible)
    if (
        len(eng_ids) > 1
        and len(comp_ids) == 1
        and engagement_id is None
        and competition_id is None
        and competition_type is None
        and poule_id is None
        and len(equipes) > 1
    ):
        # Ne déclenche que si vraiment plusieurs engagements différents pour même catégorie
        # (ex: U18M1 engagée 2 fois en PLAT phase différente mais déduplication n'a pas filtré)
        pass  # laisse passer, la déduplication a déjà réduit

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
        import unittest.mock

        import ffbb_mcp.services as svc

        from .poule import get_poule_service as poule_fn

        if isinstance(
            getattr(svc, "get_poule_service", None),
            (unittest.mock.AsyncMock, unittest.mock.MagicMock),
        ):
            poule_getter = svc.get_poule_service
        else:
            poule_getter = poule_fn

        poule = await poule_getter(pid, force_refresh=force_refresh)
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
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    numero_equipe: int | None = None,
    engagement_id: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    poule_id: int | str | None = None,
    season_id: int | str | None = None,
    force_refresh: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    from .common import _extract_phase_num

    # Compat: engagement_id peut arriver via kwargs (alias)
    if engagement_id is None:
        engagement_id = kwargs.get("engagement_id")

    error, equipes, club_resolu = await _resolve_team_equipes(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        numero_equipe=numero_equipe,
        engagement_id=engagement_id,
        competition_id=competition_id,
        competition_type=competition_type,
        poule_id=poule_id,
        not_found_status="not_found",
        force_refresh=force_refresh,
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

    # Normalisation IDs string + champs scheduled_* pour cohérence contrat
    time_confirmed = bool(_is_horaire_renseigne(next_match, next_dt))
    scheduled_date = next_dt.strftime("%Y-%m-%d") if next_dt else None
    scheduled_at = next_dt.isoformat() if (time_confirmed and next_dt) else None
    return {
        "status": "ok",
        "club_resolu": club_resolu,
        "team": source_team,
        "match": {
            "poule_id": str(source_team.get("poule_id"))
            if source_team.get("poule_id") is not None
            else None,
            "match_id": str(next_match.get("id"))
            if next_match.get("id") is not None
            else None,
            "date": next_dt.isoformat()
            if next_dt and time_confirmed
            else scheduled_date,
            "scheduled_date": scheduled_date,
            "scheduled_at": scheduled_at,
            "time_confirmed": time_confirmed,
            "horaire_renseigne": time_confirmed,
            "statut": _compute_match_statut(next_match, next_dt),
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


async def ffbb_last_result_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    numero_equipe: int = 1,
    engagement_id: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    poule_id: int | str | None = None,
    season_id: int | str | None = None,
    force_refresh: bool = False,
    **kwargs: Any,
) -> dict:
    if engagement_id is None:
        engagement_id = kwargs.get("engagement_id")
    error, equipes, club_resolu = await _resolve_team_equipes(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        numero_equipe=numero_equipe,
        engagement_id=engagement_id,
        competition_id=competition_id,
        competition_type=competition_type,
        poule_id=poule_id,
        not_found_status="no_result",
        force_refresh=force_refresh,
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
    # Normalisation date ISO8601 + scheduled_* pour cohérence
    raw_date = dernier.get("date_rencontre", "") or dernier.get("date", "")
    dt_last = _parse_dt(raw_date)
    time_confirmed_last = bool(_is_horaire_renseigne(dernier, dt_last))
    scheduled_date_last = (
        dt_last.strftime("%Y-%m-%d")
        if dt_last
        else (str(raw_date)[:10] if raw_date else None)
    )
    scheduled_at_last = (
        dt_last.isoformat() if (time_confirmed_last and dt_last) else None
    )
    iso_date_last = (
        dt_last.isoformat()
        if (time_confirmed_last and dt_last)
        else scheduled_date_last
    )

    return {
        "status": "ok",
        "club_resolu": club_resolu,
        "date": iso_date_last,
        "scheduled_date": scheduled_date_last,
        "scheduled_at": scheduled_at_last,
        "time_confirmed": time_confirmed_last,
        "horaire_renseigne": time_confirmed_last,
        "statut": _compute_match_statut(dernier, dt_last),
        "journee": dernier.get("numeroJournee"),
        "competition": competition_name,
        "competition_id": str(source_eq.get("competition_id"))
        if source_eq.get("competition_id") is not None
        else None,
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


async def ffbb_head_to_head_service(
    club_a: str | None = None,
    organisme_id_a: int | str | None = None,
    club_b: str | None = None,
    organisme_id_b: int | str | None = None,
    categorie: str | None = None,
    engagement_id: int | str | None = None,
    engagement_id_a: int | str | None = None,
    engagement_id_b: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    poule_id: int | str | None = None,
    season_id: int | str | None = None,
    force_refresh: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compare 2 équipes et analyse leurs confrontations directes (H2H), formes et stats comparatives."""
    from ..analytics import compute_head_to_head, compute_poule_advanced_stats
    from ..dynamique import compute_team_dynamique
    from .poule import get_poule_service

    # Normalisation polymorphe des arguments A et B
    eff_club_a = (
        club_a
        or kwargs.get("club_name")
        or kwargs.get("club")
        or kwargs.get("club_a_nom")
        or kwargs.get("nom_club")
    )
    eff_org_id_a = (
        organisme_id_a
        or kwargs.get("organisme_id")
        or kwargs.get("org_id")
        or kwargs.get("organisme_id_a")
    )
    eff_num_a = (
        kwargs.get("numero_equipe_a")
        if kwargs.get("numero_equipe_a") is not None
        else kwargs.get("numero_equipe")
    )

    eff_club_b = (
        club_b
        or kwargs.get("adversaire")
        or kwargs.get("opponent")
        or kwargs.get("club_adversaire")
        or kwargs.get("club_b_nom")
    )
    eff_org_id_b = (
        organisme_id_b
        or kwargs.get("adversaire_id")
        or kwargs.get("organisme_id_adversaire")
        or kwargs.get("organisme_id_b")
        or kwargs.get("org_id_b")
    )
    eff_num_b = kwargs.get("numero_equipe_b")

    eff_comp_id = competition_id or kwargs.get("competition_id")
    eff_comp_type = competition_type or kwargs.get("competition_type")
    eff_poule_id = poule_id or kwargs.get("poule_id")
    eff_eng_a = (
        engagement_id_a
        or engagement_id
        or kwargs.get("engagement_id")
        or kwargs.get("engagement_id_a")
    )
    eff_eng_b = engagement_id_b or engagement_id or kwargs.get("engagement_id_b")

    # 1. Résolution des équipes A et B
    err_a, eq_a, club_res_a = await _resolve_team_equipes(
        club_name=eff_club_a,
        organisme_id=eff_org_id_a,
        categorie=categorie,
        numero_equipe=eff_num_a,
        engagement_id=eff_eng_a,
        competition_id=eff_comp_id,
        competition_type=eff_comp_type,
        poule_id=eff_poule_id,
        not_found_status="not_found_a",
        force_refresh=force_refresh,
    )
    if err_a:
        return {
            "error": f"Équipe A ({eff_club_a or eff_org_id_a}) introuvable",
            "details": err_a,
        }

    err_b, eq_b, club_res_b = await _resolve_team_equipes(
        club_name=eff_club_b,
        organisme_id=eff_org_id_b,
        categorie=categorie,
        numero_equipe=eff_num_b,
        engagement_id=eff_eng_b,
        competition_id=eff_comp_id,
        competition_type=eff_comp_type,
        poule_id=eff_poule_id,
        not_found_status="not_found_b",
        force_refresh=force_refresh,
    )

    # Fallback par poule : si l'équipe B n'est pas résolue via engagements,
    # chercher l'adversaire par nom dans la poule de l'équipe A.
    # Cas courant : ententes, CTC, clubs dont l'engagement est rattaché
    # à une entité différente de l'organisme recherché.
    fallback_warning: str | None = None
    if err_b and eq_a:
        poules_a = {str(e["poule_id"]) for e in eq_a if e.get("poule_id")}
        if poules_a and (eff_club_b or eff_org_id_b):
            from .poule import get_poule_service

            opponent_name_norm = _normalize_name(eff_club_b or "")
            for pid in poules_a:
                poule_data = await get_poule_service(pid, force_refresh=force_refresh)
                if not isinstance(poule_data, dict):
                    continue
                rencontres = poule_data.get("rencontres") or []
                # Chercher l'adversaire par nom dans les rencontres
                found_eng_id: str | None = None
                found_name: str | None = None
                for r in rencontres:
                    if not isinstance(r, dict):
                        continue
                    for key_n, key_e in [
                        ("nomEquipe1", "idEngagementEquipe1"),
                        ("nomEquipe2", "idEngagementEquipe2"),
                    ]:
                        raw_name = str(r.get(key_n) or "")
                        if opponent_name_norm and opponent_name_norm in _normalize_name(
                            raw_name
                        ):
                            eng_raw = r.get(key_e)
                            eid = str(
                                eng_raw.get("id")
                                if isinstance(eng_raw, dict)
                                else (eng_raw or "")
                            )
                            if eid:
                                found_eng_id = eid
                                found_name = raw_name
                                break
                    if found_eng_id:
                        break
                if found_eng_id:
                    # Construire un engagement synthétique
                    eq_b = [
                        {
                            "engagement_id": found_eng_id,
                            "poule_id": pid,
                            "nom_equipe": found_name or eff_club_b,
                        }
                    ]
                    club_res_b = {"nom": found_name or eff_club_b, "_synthetic": True}
                    err_b = None
                    fallback_warning = (
                        f"L'équipe '{eff_club_b}' n'a pas pu être résolue via ses engagements club "
                        f"(possible entente/CTC). Identification par son nom dans la poule {pid}."
                    )
                    break

    if err_b:
        return {
            "error": f"Équipe B ({eff_club_b or eff_org_id_b}) introuvable",
            "details": err_b,
        }

    nom_a = (club_res_a or {}).get("nom") or eff_club_a or "Équipe A"
    nom_b = (club_res_b or {}).get("nom") or eff_club_b or "Équipe B"

    poules_a = {str(e["poule_id"]) for e in eq_a if e.get("poule_id")}
    poules_b = {str(e["poule_id"]) for e in eq_b if e.get("poule_id")}
    common_poules = poules_a.intersection(poules_b)

    target_poules = common_poules if common_poules else (poules_a.union(poules_b))
    if not target_poules:
        return {
            "status": "not_found",
            "message": f"Aucune poule trouvée pour comparer {nom_a} et {nom_b}.",
        }

    poules_raw = await asyncio.gather(
        *[get_poule_service(pid, force_refresh=force_refresh) for pid in target_poules],
        return_exceptions=True,
    )
    poules_list = [p for p in poules_raw if isinstance(p, dict)]
    all_rencontres = [r for p in poules_list for r in (p.get("rencontres", []) or [])]

    eng_ids_a = {str(e["engagement_id"]) for e in eq_a if e.get("engagement_id")}
    eng_ids_b = {str(e["engagement_id"]) for e in eq_b if e.get("engagement_id")}

    h2h_data = compute_head_to_head(
        all_rencontres,
        eng_id_a=next(iter(eng_ids_a)) if eng_ids_a else None,
        nom_a=nom_a,
        eng_id_b=next(iter(eng_ids_b)) if eng_ids_b else None,
        nom_b=nom_b,
    )

    # Forme récente
    dynamique_a = compute_team_dynamique(
        all_rencontres, eng_ids=eng_ids_a, club_nom=nom_a
    )
    dynamique_b = compute_team_dynamique(
        all_rencontres, eng_ids=eng_ids_b, club_nom=nom_b
    )

    # Stats de poule (si poule commune)
    profil_a = None
    profil_b = None
    if common_poules and poules_list:
        poule_commune = poules_list[0]
        profil_a = compute_poule_advanced_stats(
            poule_commune,
            target_eng_id=next(iter(eng_ids_a)) if eng_ids_a else None,
            club_nom=nom_a,
        )
        profil_b = compute_poule_advanced_stats(
            poule_commune,
            target_eng_id=next(iter(eng_ids_b)) if eng_ids_b else None,
            club_nom=nom_b,
        )

    # Synthèse d'avant-match pour LLM
    narrative_points = []
    if h2h_data["confrontations_count"] > 0:
        narrative_points.append(h2h_data["bilan_h2h"])
    if dynamique_a.get("forme_str"):
        label_a = (
            dynamique_a.get("serie_actuelle", {}).get("label") or ""  # type: ignore[union-attr]
        )
        narrative_points.append(
            f"Forme {nom_a} (5 derniers) : {dynamique_a['forme_str']} ({label_a})"
        )
    if dynamique_b.get("forme_str"):
        label_b = (
            dynamique_b.get("serie_actuelle", {}).get("label") or ""  # type: ignore[union-attr]
        )
        narrative_points.append(
            f"Forme {nom_b} (5 derniers) : {dynamique_b['forme_str']} ({label_b})"
        )
    if (
        profil_a
        and profil_b
        and profil_a.get("rang_attaque")
        and profil_b.get("rang_defense")
    ):
        narrative_points.append(
            f"Duel des styles : Attaque {nom_a} ({profil_a['rang_attaque']}) vs Défense {nom_b} ({profil_b['rang_defense']})"
        )
    elif not narrative_points:
        narrative_points.append(
            f"Début de saison : première confrontation officielle de la saison entre {nom_a} et {nom_b}."
        )

    result = {
        "status": "ok",
        "equipe_a": {
            "nom": nom_a,
            "club_resolu": club_res_a,
            "dynamique": dynamique_a,
            "profil": profil_a,
        },
        "equipe_b": {
            "nom": nom_b,
            "club_resolu": club_res_b,
            "dynamique": dynamique_b,
            "profil": profil_b,
        },
        "face_a_face": h2h_data,
        "points_cles_llm": narrative_points,
        "_meta": _freshness_meta(cache="poule", force_refresh_supported=True),
    }
    if fallback_warning:
        result["warning"] = fallback_warning
    return result
