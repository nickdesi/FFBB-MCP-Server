from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

from mcp.types import INTERNAL_ERROR, ErrorData

from ffbb_mcp._state import _read_positive_int_env, state
from ffbb_mcp.cache_strategy import get_poule_ttl, get_static_ttl

from .common import McpError


async def get_client_async(*args, **kwargs):
    import ffbb_mcp.client

    return await ffbb_mcp.client.get_client_async(*args, **kwargs)


from ffbb_mcp.utils import (
    format_team_name,
    jaro_winkler_similarity,
    serialize_model,
)

from .common import (
    _cache_set,
    _coerce_numeric_id,
    _dedupe_inflight,
    _dedupe_inflight_detail,
    _detect_phase_type,
    _freshness_meta,
    _normalize_name,
    _safe_call,
    _safe_call_with_inflight,
    _swr_serve,
    _with_ffbb_semaphore,
)

logger = logging.getLogger("ffbb-mcp")


async def _fetch_lives() -> list[dict]:
    client = await get_client_async()
    lives = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            "Lives (Matchs en cours)", lambda: client.get_lives_async()
        )
    )
    lives_list = lives if isinstance(lives, list) else []
    result = [serialize_model(live) for live in lives_list]
    from .salle import _enrich_matches_with_salle_details

    await _enrich_matches_with_salle_details(result)
    _cache_set(state.cache_lives, "lives", result, "lives")
    return result


def _is_live_match(m: dict[str, Any]) -> bool:
    """Détermine si un match de l'API FFBB Live est réellement en cours de jeu."""
    if not isinstance(m, dict):
        return False
    status = str(m.get("match_status") or m.get("status") or "").upper().strip()
    cur_status = str(m.get("current_status") or "").upper().strip()
    period = m.get("current_period")
    clock = m.get("clock")

    # Matchs programmés futurs ou terminés/annulés
    if status in (
        "SCHEDULED",
        "COMPLETE",
        "FINISHED",
        "TERMINE",
        "TERMINEE",
        "ABANDONED",
        "ANNULE",
        "REPORTE",
    ):
        return status == "SCHEDULED" and (
            period is not None or cur_status in ("LIVE", "IN_PROGRESS", "EN_COURS")
        )

    if status in (
        "LIVE",
        "IN_PROGRESS",
        "EN_COURS",
        "LIVE_STREAMING",
    ) or cur_status in (
        "LIVE",
        "IN_PROGRESS",
        "EN_COURS",
    ):
        return True

    if (
        status.startswith("QUARTER")
        or status.startswith("PERIOD")
        or "TIME" in status
        or "TEMPS" in status
        or "OVERTIME" in status
    ):
        return True

    return period is not None or (
        clock is not None and str(clock).strip() not in ("", "00:00")
    )


async def get_lives_service(
    include_scheduled: bool = False,
    *,
    organisme_id: int | str | None = None,
    club_name: str | None = None,
    categorie: str | None = None,
    numero_equipe: int | None = None,
    engagement_id: int | str | None = None,
    include_calendar_fallback: bool = True,
) -> list[dict]:
    ttl = _read_positive_int_env("FFBB_CACHE_TTL_LIVES", get_static_ttl("lives"))
    raw_lives = await _swr_serve(state.cache_lives, "lives", "lives", ttl, _fetch_lives)
    target_requested = any(
        value is not None and value != ""
        for value in (organisme_id, club_name, categorie, numero_equipe, engagement_id)
    )
    if not target_requested:
        if include_scheduled or not raw_lives:
            return raw_lives
        return [m for m in raw_lives if _is_live_match(m)]

    target_engagement = str(engagement_id or "")
    target_organisme = str(organisme_id or "")

    def _match_id(value: Any) -> str:
        # Les rencontres portent les ids dans des dicts (idEngagementEquipe1.id) :
        # str(dict) ne matcherait jamais l'id demandé.
        if isinstance(value, dict):
            value = value.get("id")
        return str(value or "")

    def matches_target(match: dict[str, Any]) -> bool:
        engagement_values = {
            _match_id(match.get(key))
            for key in (
                "engagement_id",
                "id_engagement",
                "idEngagementEquipe1",
                "idEngagementEquipe2",
            )
        }
        organisme_values = {
            _match_id(match.get(key))
            for key in (
                "organisme_id",
                "id_organisme",
                "idOrganismeEquipe1",
                "idOrganismeEquipe2",
            )
        }
        team_names = " ".join(
            str(match.get(key) or "")
            for key in (
                "equipe1",
                "equipe2",
                "nomEquipe1",
                "nomEquipe2",
                "team_label",
            )
        )
        if target_engagement and target_engagement in engagement_values:
            return True
        if target_organisme and target_organisme in organisme_values:
            return True
        if club_name and _normalize_name(club_name) in _normalize_name(team_names):
            return True
        return not (target_engagement or target_organisme or club_name)

    selected = [
        dict(match)
        for match in raw_lives
        if matches_target(match) and (include_scheduled or _is_live_match(match))
    ]
    for match in selected:
        if _is_live_match(match):
            match.setdefault("canonical_status", "live")
            match.setdefault("temporal_status", "live")
            match.setdefault("status_confidence", "high")
            match.setdefault(
                "status_explanation",
                "Statut live explicitement remonté par la FFBB.",
            )

    if not include_calendar_fallback:
        return selected

    from .calendar import get_calendrier_club_service

    # Le fallback calendrier doit respecter include_scheduled : avec ["live"]
    # seul, une poule sans match en cours n'apportait jamais les programmés.
    calendar_kwargs: dict[str, Any] = {
        "status_filter": ["live", "scheduled"] if include_scheduled else ["live"],
        "scope": "team" if engagement_id or categorie or numero_equipe else "club",
    }
    for key, value in (
        ("organisme_id", organisme_id),
        ("club_name", club_name),
        ("categorie", categorie),
        ("numero_equipe", numero_equipe),
        ("engagement_id", engagement_id),
    ):
        if value is not None and value != "":
            calendar_kwargs[key] = value

    calendar = await get_calendrier_club_service(**calendar_kwargs)
    calendar_items = calendar.get("items", []) if isinstance(calendar, dict) else []
    known_ids = {
        str(match.get("id") or match.get("match_id") or "") for match in selected
    }
    for match in calendar_items:
        match_id = str(match.get("id") or match.get("match_id") or "")
        if match_id and match_id in known_ids:
            continue
        selected.append(match)
        if match_id:
            known_ids.add(match_id)
    return selected


_SAISONS_FIELDS = ["id", "libelle", "code", "actif", "debut", "fin", "enCours"]


async def _fetch_saisons(active_only: bool) -> list[dict]:
    from datetime import datetime

    client = await get_client_async()
    filter_criteria = '{"actif": {"_eq": true}}' if active_only else None
    saisons = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            "Saisons",
            lambda: client.get_saisons_async(
                fields=_SAISONS_FIELDS, filter_criteria=filter_criteria
            ),
        )
    )
    saisons_list = saisons if isinstance(saisons, list) else []
    today_str = datetime.now().strftime("%Y-%m-%d")
    result: list[dict] = []
    for s in saisons_list:
        d = serialize_model(s)
        if isinstance(d, dict):
            # Aliases season_id & label pour cohérence avec les paramètres MCP et attentes clients
            if "id" in d and "season_id" not in d:
                d["season_id"] = str(d["id"])
            if "libelle" in d and "label" not in d:
                d["label"] = str(d["libelle"])
            debut = str(d.get("debut") or d.get("dateDebut") or "")
            fin = str(d.get("fin") or d.get("dateFin") or "")
            is_within_range = bool(debut and fin and debut <= today_str <= fin)
            d["within_date_range"] = is_within_range
            # Si la saison est active et dans la plage calendaire courante, enCours est déterministement True
            is_active = bool(d.get("actif") or d.get("active"))
            if is_within_range and is_active:
                d["enCours"] = True
            result.append(d)
        else:
            result.append(d)
    _cache_set(state.cache_saisons, f"saisons:{active_only}", result, "saisons")
    return result


async def get_saisons_service(
    active_only: bool = False, force_refresh: bool = False
) -> list[dict]:
    cache_key = f"saisons:{active_only}"
    ttl = _read_positive_int_env("FFBB_CACHE_TTL_DETAIL", get_static_ttl("saisons"))
    if force_refresh and state.cache_saisons is not None:
        state.cache_saisons.pop(cache_key, None)
    return await _swr_serve(
        state.cache_saisons,
        cache_key,
        "saisons",
        ttl,
        lambda: _fetch_saisons(active_only),
    )


async def get_competition_service(competition_id: int | str) -> dict:
    competition_id_int = _coerce_numeric_id(competition_id, "competition_id")
    cache_key = f"competition:{competition_id_int}"

    async def _fetch() -> dict:
        client = await get_client_async()
        comp = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Competition {competition_id_int}",
                lambda: client.get_competition_async(competition_id=competition_id_int),
            ),
        )
        return serialize_model(comp) or {}

    return await _dedupe_inflight_detail(
        cache_key,
        _fetch,
        cache_name="competition",
        cache=state.cache_competition,
    )


async def get_poule_service(
    poule_id: int | str, *, force_refresh: bool = False
) -> dict:
    poule_id_int = _coerce_numeric_id(poule_id, "poule_id")
    cache_key = f"poule:{poule_id_int}"

    if force_refresh:
        if state.cache_poule is not None:
            state.cache_poule.pop(cache_key, None)
        if state.cache_classement is not None:
            if hasattr(state.cache_classement, "delete_prefix"):
                state.cache_classement.delete_prefix(f"classement:{poule_id_int}")
            elif hasattr(state.cache_classement, "keys"):
                for k in list(state.cache_classement.keys()):
                    if str(k).startswith(f"classement:{poule_id_int}"):
                        state.cache_classement.pop(k, None)
            else:
                state.cache_classement.pop(f"classement:{poule_id_int}", None)

    ttl = await get_poule_ttl(poule_id_int, get_lives_service)

    async def _fetch() -> dict:
        client = await get_client_async()
        poule = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Poule {poule_id_int}",
                lambda: client.get_poule_async(poule_id=poule_id_int),
            ),
        )
        data = serialize_model(poule) or {}

        rencontres = data.get("rencontres") or []
        restantes_par_equipe: dict[str, list[dict]] = {}
        for r in rencontres:
            if r.get("joue") not in (0, "0"):
                continue
            for side in ("nomEquipe1", "nomEquipe2"):
                nom = r.get(side, "")
                if nom:
                    if nom not in restantes_par_equipe:
                        restantes_par_equipe[nom] = []
                    restantes_par_equipe[nom].append(
                        {
                            "id": r.get("id"),
                            "date": r.get("date_rencontre"),
                            "domicile": r.get("nomEquipe1"),
                            "exterieur": r.get("nomEquipe2"),
                            "journee": r.get("numeroJournee"),
                        }
                    )
        data["rencontres_restantes_par_equipe"] = restantes_par_equipe
        data["phase_terminee"] = len(restantes_par_equipe) == 0
        comp_name = data.get("nom") or data.get("libelle") or ""
        data["phase_type"] = _detect_phase_type(comp_name)

        return {"_ttl": ttl, "data": data}

    result = await _dedupe_inflight(
        cache=state.cache_poule,
        cache_key=cache_key,
        inflight_map=state.inflight_poule,
        make_coro=_fetch,
        cache_name="poule",
        swr_ttl=ttl,
    )

    if isinstance(result, dict) and "data" in result:
        rencontres = result["data"].get("rencontres") or []
        if rencontres:
            result["data"]["rencontres"] = sorted(
                rencontres,
                key=lambda r: (
                    r.get("date_reelle") or "9999",
                    r.get("heure_reelle") or "9999",
                ),
            )

    return (
        result.get("data", result)
        if isinstance(result, dict) and "_ttl" in result
        else result
    )


async def format_poule_response(poule_data: dict) -> dict[str, Any]:
    classements = poule_data.get("classements") or []
    formatted_classements = []
    for c in classements or []:
        eng = c.get("id_engagement") or {}
        nom = eng.get("nom", "")
        num = eng.get("numero_equipe")
        c["equipe"] = format_team_name(nom, num)
        logo_id = (eng.get("logo") or {}).get("id")
        c["logo_url"] = (
            f"https://api.ffbb.com/assets/{logo_id}?height=220&fit=contain&format=avif"
            if logo_id
            else None
        )
        formatted_classements.append(c)

    rencontres = poule_data.get("rencontres") or []
    formatted_rencontres = []
    for m in rencontres or []:
        eng1 = m.get("idEngagementEquipe1") or {}
        eng2 = m.get("idEngagementEquipe2") or {}
        num1 = eng1.get("numeroEquipe") if isinstance(eng1, dict) else None
        num2 = eng2.get("numeroEquipe") if isinstance(eng2, dict) else None
        m["nomEquipe1"] = format_team_name(m.get("nomEquipe1", ""), num1)
        m["nomEquipe2"] = format_team_name(m.get("nomEquipe2", ""), num2)
        formatted_rencontres.append(m)

    from .salle import _enrich_matches_with_salle_details

    await _enrich_matches_with_salle_details(formatted_rencontres)

    # Synthèse robuste du nom de poule : l'API FFBB renvoie parfois libelle=None
    # avant J1 (ex: U13M2). On reconstruit depuis competition/poule_id pour
    # éviter "Salle non encore renseignée" côté agent.
    poule_libelle = (
        poule_data.get("libelle")
        or poule_data.get("nom")
        or poule_data.get("competition")
        or ""
    )
    if not poule_libelle:
        pid = poule_data.get("id")
        poule_libelle = f"Poule {pid}" if pid else "Poule"
    res: dict[str, Any] = {
        "id": str(poule_data.get("id")) if poule_data.get("id") is not None else None,
        "nom": poule_libelle,
        "classements": formatted_classements,
        "rencontres": formatted_rencontres,
        "_meta": _freshness_meta(
            cache="poule",
            ttl_seconds=poule_data.get("_ttl_seconds"),
            force_refresh_supported=True,
        ),
    }
    if formatted_rencontres:
        import ffbb_mcp.services

        max_limit = getattr(ffbb_mcp.services, "_MAX_CALENDAR_MATCHES", 300)
        total_matches = len(formatted_rencontres)
        if total_matches > max_limit:
            truncated_rencontres = formatted_rencontres[:max_limit]
            truncated_rencontres.append(
                {
                    "warning": f"Résultat tronqué. Seulement {max_limit} rencontres sur {total_matches} affichées."
                }
            )
            res["rencontres"] = truncated_rencontres
            res["_truncated"] = True
            res["_omitted_count"] = total_matches - max_limit
            res["_total"] = total_matches
    return res


async def get_organisme_service(
    organisme_id: int | str,
    force_refresh: bool = False,
    **kwargs: Any,
) -> dict:
    organisme_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    cache_key = f"organisme:{organisme_id_int}"

    if force_refresh and state.cache_organisme is not None:
        state.cache_organisme.pop(cache_key, None)
        if state.cache_equipes is not None:
            if hasattr(state.cache_equipes, "delete_prefix"):
                state.cache_equipes.delete_prefix(f"equipes:{organisme_id_int}:")
            elif hasattr(state.cache_equipes, "keys"):
                keys_to_pop = [
                    k
                    for k in list(state.cache_equipes.keys())
                    if str(k).startswith(f"equipes:{organisme_id_int}:")
                ]
                for k in keys_to_pop:
                    state.cache_equipes.pop(k, None)

    async def _fetch() -> dict:
        client = await get_client_async()
        org = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Organisme {organisme_id_int}",
                lambda: client.get_organisme_async(organisme_id=organisme_id_int),
            ),
        )
        data = serialize_model(org) or {}
        if not data.get("nom") and not data.get("engagements"):
            raise McpError(
                error=ErrorData(
                    code=INTERNAL_ERROR,
                    message=f"Organisme_id {organisme_id_int} introuvable ou vide.",
                )
            )
        return data

    return await _dedupe_inflight_detail(
        cache_key,
        _fetch,
        cache_name="organisme",
        cache=state.cache_organisme,
    )


async def ffbb_get_classement_service(
    poule_id: int | str,
    *,
    force_refresh: bool = False,
    target_organisme_id: int | str | None = None,
    target_num: int | str | None = None,
) -> list[dict[str, Any]]:
    poule_id_int = _coerce_numeric_id(poule_id, "poule_id")
    cache_key = (
        f"classement:{poule_id_int}:{target_organisme_id or ''}:{target_num or ''}"
    )

    if force_refresh:
        if state.cache_classement is not None:
            state.cache_classement.pop(cache_key, None)
        if state.cache_poule is not None:
            state.cache_poule.pop(f"poule:{poule_id_int}", None)

    ttl = await get_poule_ttl(poule_id_int, get_lives_service)

    async def _fetch() -> dict[str, Any]:
        client = await get_client_async()
        poule = await _with_ffbb_semaphore(
            _safe_call(
                f"Classement poule {poule_id_int}",
                lambda: client.get_poule_async(poule_id=poule_id_int),
            )
        )
        if not poule:
            return {"_ttl": ttl, "data": []}
        data = serialize_model(poule)
        raw = data.get("classements", data.get("classement") or []) or []
        if not isinstance(raw, list):
            raw = []

        flat: list[dict[str, Any]] = []
        target_org_str = str(target_organisme_id) if target_organisme_id else None
        target_num_str = str(target_num) if target_num else None

        for c in raw:
            if not isinstance(c, dict):
                continue
            eng = c.get("id_engagement") or {}
            nom_equipe = eng.get("nom", "")
            num_equipe = eng.get("numero_equipe")
            org_id = str(c.get("organisme_id") or eng.get("organisme_id") or "")

            is_target = False
            if target_org_str and org_id == target_org_str:
                if target_num_str:
                    curr_num = str(num_equipe or "")
                    if curr_num == target_num_str or not curr_num:
                        is_target = True
                else:
                    is_target = True

            logo_id = c.get("organisme_logo_id") or (eng.get("logo") or {}).get("id")
            logo_url = (
                f"https://api.ffbb.com/assets/{logo_id}?height=220&fit=contain&format=avif"
                if logo_id
                else None
            )

            mj_raw = c.get("match_joues")
            try:
                mj_int = int(mj_raw) if mj_raw is not None else 0
            except (TypeError, ValueError):
                mj_int = 0
            quotient_val = None if mj_int == 0 else c.get("quotient")

            flat.append(
                {
                    "position": c.get("position"),
                    "equipe": format_team_name(nom_equipe, num_equipe),
                    "points": c.get("points"),
                    "match_joues": c.get("match_joues"),
                    "gagnes": c.get("gagnes"),
                    "perdus": c.get("perdus"),
                    "difference": c.get("difference"),
                    "is_target": is_target,
                    "paniers_marques": c.get("paniers_marques") or 0,
                    "paniers_encaisses": c.get("paniers_encaisses") or 0,
                    "logo_url": logo_url,
                    "point_initiaux": c.get("point_initiaux"),
                    "penalites_arbitrage": c.get("penalites_arbitrage"),
                    "penalites_entraineur": c.get("penalites_entraineur"),
                    "penalites_diverses": c.get("penalites_diverses"),
                    "nombre_forfaits": c.get("nombre_forfaits"),
                    "nombre_defauts": c.get("nombre_defauts"),
                    "quotient": quotient_val,
                    "hors_classement": c.get("hors_classement"),
                }
            )

        # Fallback si aucun classement calculé (avant début de saison) : extraire les équipes des rencontres
        if not flat and data.get("rencontres"):
            # Récupération du nom du club cible pour matching par nom (robuste pré-saison)
            target_nom = None
            if target_org_str:
                try:
                    _org_data = await get_organisme_service(target_org_str)
                    target_nom = (
                        _org_data.get("nom", "")
                        if isinstance(_org_data, dict)
                        else None
                    )
                except Exception:
                    target_nom = None
            seen_teams: set[str] = set()
            pos = 1
            for r in data.get("rencontres") or []:
                for eq_key in ("nomEquipe1", "nomEquipe2"):
                    eq_name = r.get(eq_key)
                    if eq_name and eq_name not in seen_teams:
                        seen_teams.add(eq_name)
                        is_target = False
                        if target_nom and _normalize_name(
                            target_nom
                        ) in _normalize_name(eq_name):
                            # Vérifie aussi le numéro si fourni
                            if target_num_str:
                                # Extrait le numéro de l'équipe depuis eq_name
                                from ffbb_mcp.services.club import _match_team_name

                                if _match_team_name(
                                    eq_name,
                                    target_nom,
                                    int(target_num_str)
                                    if target_num_str.isdigit()
                                    else None,
                                ):
                                    is_target = True
                            else:
                                is_target = True
                        elif target_org_str and str(target_org_str) in str(
                            r.get("idOrganisme", "")
                        ):
                            is_target = True
                        flat.append(
                            {
                                "position": pos,
                                "equipe": eq_name,
                                "points": 0,
                                "match_joues": 0,
                                "gagnes": 0,
                                "perdus": 0,
                                "difference": 0,
                                "is_target": is_target,
                                "paniers_marques": 0,
                                "paniers_encaisses": 0,
                                "logo_url": None,
                                "point_initiaux": None,
                                "penalites_arbitrage": None,
                                "penalites_entraineur": None,
                                "penalites_diverses": None,
                                "nombre_forfaits": None,
                                "nombre_defauts": None,
                                "quotient": None,
                                "hors_classement": None,
                                "status": "non_commence",
                            }
                        )
                        pos += 1

        # Normalisation du champ position en entier et tri numérique natif croissant
        for item in flat:
            pos_val = item.get("position")
            if pos_val is not None:
                with contextlib.suppress(ValueError, TypeError):
                    item["position"] = int(pos_val)

        def _position_sort_key(item: dict[str, Any]) -> tuple[int, int]:
            pos = item.get("position")
            if isinstance(pos, int):
                return (0, pos)
            try:
                if pos is not None:
                    return (0, int(pos))
            except (ValueError, TypeError):
                pass
            return (1, 999999)

        flat.sort(key=_position_sort_key)

        return {"_ttl": ttl, "data": flat}

    wrapped = await _dedupe_inflight(
        cache=state.cache_classement,
        cache_key=cache_key,
        inflight_map=state.inflight_classement,
        make_coro=_fetch,
        cache_name="classement",
        swr_ttl=ttl,
    )
    if isinstance(wrapped, dict) and "data" in wrapped:
        data_res = wrapped["data"]
        return data_res if isinstance(data_res, list) else []
    return wrapped if isinstance(wrapped, list) else []


async def find_team_poule_service(
    competition_id: int | str,
    organisme_id_or_name: int | str,
) -> dict[str, Any]:
    """Localise la poule d'un club/équipe dans une compétition multi-poules.

    Cherche d'abord dans les engagements de l'organisme (ultra-rapide, 1 appel).
    En fallback, inspecte les classements des poules de la compétition.
    """
    comp_id_int = _coerce_numeric_id(competition_id, "competition_id")
    comp_id_str = str(comp_id_int)

    org_id: str | None = None
    club_nom = str(organisme_id_or_name)
    org_data: dict[str, Any] | None = None

    if str(organisme_id_or_name).strip().isdigit():
        org_id = str(organisme_id_or_name).strip()
        org_data = await get_organisme_service(org_id)
        if org_data and isinstance(org_data, dict):
            club_nom = org_data.get("nom", club_nom)
    else:
        from .search import resolve_club_and_org

        resolved, org_data = await resolve_club_and_org(
            club_name=str(organisme_id_or_name), organisme_id=None
        )
        if resolved:
            org_id = str(resolved[0].get("organisme_id"))
            club_nom = resolved[0].get("nom", club_nom)
            if not org_data:
                org_data = await get_organisme_service(org_id)

    # 1. Fast-path : vérification directe dans les engagements du club
    if org_data and isinstance(org_data, dict):
        for eng in org_data.get("engagements") or []:
            if not isinstance(eng, dict):
                continue
            comp = eng.get("idCompetition") or {}
            if str(comp.get("id")) == comp_id_str:
                poule = eng.get("idPoule") or {}
                poule_id = str(poule.get("id"))
                poule_nom = poule.get("nom")
                if not poule_nom:
                    comp_data = await get_competition_service(comp_id_str)
                    for p in comp_data.get("poules") or []:
                        if str(p.get("id")) == poule_id:
                            poule_nom = p.get("nom")
                            break
                comp_nom = comp.get("nom") or ""
                num = eng.get("numeroEquipe") or ""
                cat = (comp.get("categorie") or {}).get("code", "")
                sexe = comp.get("sexe", "")
                team_label = f"{cat}{sexe}{num}".strip()
                return {
                    "status": "found",
                    "poule_id": poule_id,
                    "poule_nom": poule_nom or f"Poule {poule_id}",
                    "competition_id": comp_id_str,
                    "competition_nom": comp_nom,
                    "organisme_id": org_id,
                    "club": club_nom,
                    "team_label": team_label or None,
                }

    # 2. Fallback : inspection des classements de chaque poule de la compétition
    comp_data = await get_competition_service(comp_id_str)
    comp_nom = comp_data.get("nom", "")
    poules = comp_data.get("poules") or []

    for p in poules:
        p_id = p.get("id")
        if not p_id:
            continue
        poule_data = await get_poule_service(p_id)
        for c in poule_data.get("classements") or []:
            c_org_id = str(c.get("organisme_id") or "")
            c_eng = c.get("id_engagement") or {}
            c_name = _normalize_name(c_eng.get("nom") or c.get("organisme_nom") or "")
            target_norm = _normalize_name(club_nom)
            if (org_id and c_org_id == org_id) or (
                target_norm and target_norm in c_name
            ):
                return {
                    "status": "found",
                    "poule_id": str(p_id),
                    "poule_nom": p.get("nom") or f"Poule {p_id}",
                    "competition_id": comp_id_str,
                    "competition_nom": comp_nom,
                    "organisme_id": c_org_id or org_id,
                    "club": c_eng.get("nom") or club_nom,
                    "team_label": c_eng.get("numero_equipe") or None,
                }

        # Fallback si les classements sont vides (ex: pré-saison avant la 1ère journée)
        if not poule_data.get("classements"):
            for r in poule_data.get("rencontres") or []:
                eq1 = _normalize_name(r.get("nomEquipe1") or "")
                eq2 = _normalize_name(r.get("nomEquipe2") or "")
                target_norm = _normalize_name(club_nom)
                if target_norm and (target_norm in eq1 or target_norm in eq2):
                    team_lbl = (
                        r.get("nomEquipe1")
                        if target_norm in eq1
                        else r.get("nomEquipe2")
                    )
                    return {
                        "status": "found",
                        "poule_id": str(p_id),
                        "poule_nom": p.get("nom") or f"Poule {p_id}",
                        "competition_id": comp_id_str,
                        "competition_nom": comp_nom,
                        "organisme_id": org_id,
                        "club": club_nom,
                        "team_label": team_lbl,
                    }

    return {
        "status": "not_found",
        "message": (
            f"Club '{organisme_id_or_name}' non trouvé dans les poules de la compétition "
            f"{comp_nom or comp_id_str}."
        ),
        "competition_id": comp_id_str,
        "competition_nom": comp_nom,
    }


_PREFIX_CLEAN_RE = re.compile(r"^(IE\s*-\s*|CTC\s+|ENT\.\s*|ENTENTE\s+)", re.IGNORECASE)


def _clean_team_for_match(name: str) -> str:
    norm = _normalize_name(name)
    return _PREFIX_CLEAN_RE.sub("", norm).strip()


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
        c_eng = c.get("id_engagement") or {}
        c_eng_id = str(c_eng.get("id") or "") if c_eng.get("id") is not None else None
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


async def get_engagement_service(
    engagement_id: int | str, *, force_refresh: bool = False
) -> dict[str, Any]:
    """Récupère les détails d'un engagement FFBB (équipe, club, poule, rencontres)."""
    eng_id_int = _coerce_numeric_id(engagement_id, "engagement_id")
    eng_id_str = str(eng_id_int)
    cache_key = f"engagement:{eng_id_str}"

    if force_refresh and state.cache_engagement is not None:
        state.cache_engagement.pop(cache_key, None)

    async def _fetch() -> dict[str, Any]:
        client = await get_client_async()
        eng = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Engagement {eng_id_str}",
                lambda: client.get_engagement_async(eng_id_str),
            ),
        )
        if not eng:
            return {"error": f"Engagement '{eng_id_str}' introuvable."}

        eng_dict = serialize_model(eng) or {}
        org_id = str(eng_dict.get("idOrganisme") or "")
        comp_id = str(eng_dict.get("idCompetition") or "")
        poule_id = str(eng_dict.get("idPoule") or "")
        num_eq = eng_dict.get("numeroEquipe") or None

        club_info: dict[str, Any] | None = None
        team_info: dict[str, Any] | None = None

        if org_id:
            try:
                org_data = await get_organisme_service(org_id)
                if org_data and isinstance(org_data, dict):
                    club_info = {
                        "id": org_id,
                        "nom": org_data.get("nom"),
                        "code": org_data.get("code"),
                    }
                from .club import ffbb_equipes_club_service

                teams = await ffbb_equipes_club_service(organisme_id=org_id)
                for t in teams:
                    if (
                        str(t.get("engagement_id") or t.get("team_id") or "")
                        == eng_id_str
                    ):
                        team_info = t
                        break
            except Exception as e:
                logger.warning(
                    "Erreur enrichissement organisme pour engagement %s: %s",
                    eng_id_str,
                    e,
                )

        poule_info: dict[str, Any] | None = None
        classement_info: dict[str, Any] | None = None
        matches: list[dict[str, Any]] = []

        if poule_id:
            try:
                poule_data = await get_poule_service(
                    poule_id, force_refresh=force_refresh
                )
                if poule_data and isinstance(poule_data, dict):
                    poule_info = {
                        "id": poule_id,
                        "nom": poule_data.get("nom"),
                        "competition_id": poule_data.get("idCompetition") or comp_id,
                    }
                    target_names: set[str] = set()
                    if team_info and team_info.get("club"):
                        target_names.add(str(team_info["club"]))
                    if club_info and club_info.get("nom"):
                        target_names.add(str(club_info["nom"]))

                    for c in poule_data.get("classements") or []:
                        c_eng = c.get("id_engagement") or {}
                        if str(c_eng.get("id") or "") == eng_id_str:
                            classement_info = c
                            if c_eng.get("nom"):
                                target_names.add(str(c_eng["nom"]))
                            if c.get("organisme_nom"):
                                target_names.add(str(c["organisme_nom"]))

                    for m in poule_data.get("rencontres") or []:
                        id1 = str(m.get("idEngagementEquipe1") or "")
                        id2 = str(m.get("idEngagementEquipe2") or "")
                        n1 = m.get("nomEquipe1") or ""
                        n2 = m.get("nomEquipe2") or ""
                        if eng_id_str in (id1, id2) or (
                            target_names and (n1 in target_names or n2 in target_names)
                        ):
                            matches.append(m)
            except Exception as e:
                logger.warning(
                    "Erreur enrichissement poule pour engagement %s: %s",
                    eng_id_str,
                    e,
                )

        return {
            "id": eng_id_str,
            "numero_equipe": num_eq,
            "organisme_id": org_id,
            "competition_id": comp_id,
            "poule_id": poule_id,
            "club": club_info,
            "team": team_info,
            "poule": poule_info,
            "classement": classement_info,
            "calendrier": matches,
            "total_matchs": len(matches),
        }

    return await _dedupe_inflight_detail(
        cache_key,
        _fetch,
        cache_name="engagement",
        cache=state.cache_engagement,
    )
