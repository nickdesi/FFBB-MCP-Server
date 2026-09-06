from __future__ import annotations

import contextlib
import logging
from typing import Any

from mcp.shared.exceptions import ErrorData, McpError
from mcp.types import INTERNAL_ERROR

from ffbb_mcp._state import _read_positive_int_env, state
from ffbb_mcp.cache_strategy import get_poule_ttl, get_static_ttl


async def get_client_async(*args, **kwargs):
    import ffbb_mcp.client

    return await ffbb_mcp.client.get_client_async(*args, **kwargs)


from ffbb_mcp.utils import format_team_name, serialize_model

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


async def get_lives_service() -> list[dict]:
    ttl = _read_positive_int_env("FFBB_CACHE_TTL_LIVES", get_static_ttl("lives"))
    return await _swr_serve(state.cache_lives, "lives", "lives", ttl, _fetch_lives)


_SAISONS_FIELDS = ["id", "libelle", "code", "actif", "debut", "fin", "enCours"]


async def _fetch_saisons(active_only: bool) -> list[dict]:
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
    result = [serialize_model(s) for s in saisons_list]
    _cache_set(state.cache_saisons, f"saisons:{active_only}", result, "saisons")
    return result


async def get_saisons_service(active_only: bool = False) -> list[dict]:
    cache_key = f"saisons:{active_only}"
    ttl = _read_positive_int_env("FFBB_CACHE_TTL_DETAIL", get_static_ttl("saisons"))
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

    if force_refresh and state.cache_poule is not None:
        state.cache_poule.pop(cache_key, None)

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

        rencontres = data.get("rencontres", []) or []
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
        rencontres = result["data"].get("rencontres", [])
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
    classements = poule_data.get("classements", [])
    formatted_classements = []
    for c in classements or []:
        eng = c.get("id_engagement", {}) or {}
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

    rencontres = poule_data.get("rencontres", [])
    formatted_rencontres = []
    for m in rencontres or []:
        eng1 = m.get("idEngagementEquipe1", {}) or {}
        eng2 = m.get("idEngagementEquipe2", {}) or {}
        num1 = eng1.get("numeroEquipe") if isinstance(eng1, dict) else None
        num2 = eng2.get("numeroEquipe") if isinstance(eng2, dict) else None
        m["nomEquipe1"] = format_team_name(m.get("nomEquipe1", ""), num1)
        m["nomEquipe2"] = format_team_name(m.get("nomEquipe2", ""), num2)
        formatted_rencontres.append(m)

    from .salle import _enrich_matches_with_salle_details

    await _enrich_matches_with_salle_details(formatted_rencontres)

    res: dict[str, Any] = {
        "id": poule_data.get("id"),
        "nom": poule_data.get("libelle"),
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


async def get_organisme_service(organisme_id: int | str) -> dict:
    organisme_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    cache_key = f"organisme:{organisme_id_int}"

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

    if force_refresh and state.cache_classement is not None:
        state.cache_classement.pop(cache_key, None)

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
        raw = data.get("classements", data.get("classement", [])) or []
        if not isinstance(raw, list):
            raw = []

        flat: list[dict[str, Any]] = []
        target_org_str = str(target_organisme_id) if target_organisme_id else None
        target_num_str = str(target_num) if target_num else None

        for c in raw:
            if not isinstance(c, dict):
                continue
            eng = c.get("id_engagement", {}) or {}
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
                    "quotient": c.get("quotient"),
                    "hors_classement": c.get("hors_classement"),
                }
            )

        # Fallback si aucun classement calculé (avant début de saison) : extraire les équipes des rencontres
        if not flat and data.get("rencontres"):
            seen_teams: set[str] = set()
            pos = 1
            for r in data.get("rencontres", []):
                for eq_key in ("nomEquipe1", "nomEquipe2"):
                    eq_name = r.get(eq_key)
                    if eq_name and eq_name not in seen_teams:
                        seen_teams.add(eq_name)
                        is_target = False
                        if target_org_str and str(target_org_str) in str(
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
            except ValueError, TypeError:
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
    return (
        wrapped["data"] if isinstance(wrapped, dict) and "data" in wrapped else wrapped
    )


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
        for eng in org_data.get("engagements", []):
            if not isinstance(eng, dict):
                continue
            comp = eng.get("idCompetition") or {}
            if str(comp.get("id")) == comp_id_str:
                poule = eng.get("idPoule") or {}
                poule_id = str(poule.get("id"))
                poule_nom = poule.get("nom")
                if not poule_nom:
                    comp_data = await get_competition_service(comp_id_str)
                    for p in comp_data.get("poules", []):
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
    poules = comp_data.get("poules", [])

    for p in poules:
        p_id = p.get("id")
        if not p_id:
            continue
        poule_data = await get_poule_service(p_id)
        for c in poule_data.get("classements", []):
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
            for r in poule_data.get("rencontres", []):
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
