from __future__ import annotations

import logging
from typing import Any

from ffbb_mcp._state import state
from ffbb_mcp.cache_strategy import get_poule_ttl


async def get_client_async(*args, **kwargs):
    import ffbb_mcp.client

    return await ffbb_mcp.client.get_client_async(*args, **kwargs)


from ffbb_mcp.utils import format_team_name, serialize_model

from .common import (
    _cache_get,
    _cache_set,
    _coerce_numeric_id,
    _dedupe_inflight,
    _dedupe_inflight_detail,
    _detect_phase_type,
    _freshness_meta,
    _safe_call,
    _safe_call_with_inflight,
    _with_ffbb_semaphore,
)

logger = logging.getLogger("ffbb-mcp")


async def get_lives_service() -> list[dict]:
    cached = _cache_get(state.cache_lives, "lives", "lives")
    if cached is not None:
        logger.debug("Cache hit: lives")
        return cached

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


async def get_saisons_service(active_only: bool = False) -> list[dict]:
    cache_key = f"saisons:{active_only}"
    cached = _cache_get(state.cache_saisons, cache_key, "saisons")
    if cached is not None:
        return cached

    client = await get_client_async()
    filter_criteria = '{"actif": {"$eq": true}}' if active_only else None
    saisons = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            "Saisons", lambda: client.get_saisons_async(filter_criteria=filter_criteria)
        )
    )
    saisons_list = saisons if isinstance(saisons, list) else []
    result = [serialize_model(s) for s in saisons_list]
    _cache_set(state.cache_saisons, cache_key, result, "saisons")
    return result


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
                    restantes_par_equipe.setdefault(nom, []).append(
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

        ttl = await get_poule_ttl(poule_id_int, get_lives_service)
        return {"_ttl": ttl, "data": data}

    result = await _dedupe_inflight(
        cache=state.cache_poule,
        cache_key=cache_key,
        inflight_map=state.inflight_poule,
        make_coro=_fetch,
        cache_name="poule",
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
        return serialize_model(org) or {}

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

    cached = _cache_get(state.cache_classement, cache_key, "classement")
    if cached is not None:
        return (
            cached["data"] if isinstance(cached, dict) and "data" in cached else cached
        )

    client = await get_client_async()
    poule = await _with_ffbb_semaphore(
        _safe_call(
            f"Classement poule {poule_id_int}",
            lambda: client.get_poule_async(poule_id=poule_id_int),
        )
    )
    if not poule:
        return []
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
    ttl = await get_poule_ttl(poule_id_int, get_lives_service)
    wrapped_flat = {"_ttl": ttl, "data": flat}
    _cache_set(state.cache_classement, cache_key, wrapped_flat, "classement")
    return flat
