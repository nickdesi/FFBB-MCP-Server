"""Calendrier complet — extrait de :mod:`ffbb_mcp.services.club`.

Isole le pipeline le plus lourd du monolithe (≈ 600 lignes,
cyclo 153) : construction du calendrier, pagination, enrichissement
salle/adresse, filtres adversaire/dates.

Imports croisés (``club``/``poule``/``search``) faits en lazy pour
éviter les cycles à l'import.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import httpx
from pydantic import ValidationError

from ffbb_mcp._state import state
from ffbb_mcp.models import CalendrierMatch
from ffbb_mcp.utils import format_team_name

from .common import _PARIS_TZ as _TZ
from .common import (
    _compute_match_statut,
    _detect_phase_type,
    _is_horaire_renseigne,
    _normalize_name,
    _parse_dt,
)

logger = logging.getLogger("ffbb-mcp")


def _get_max_calendar_matches() -> int:
    import ffbb_mcp.services as _svc

    return getattr(_svc, "_MAX_CALENDAR_MATCHES", 300)


def _engagement_numero(eng: Any) -> Any:
    return eng.get("numeroEquipe") if isinstance(eng, dict) else None


def _dedup_equipes_by_engagement_local(
    equipes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for e in equipes:
        if not isinstance(e, dict):
            continue
        eid = e.get("engagement_id")
        if eid is None:
            deduped.append(e)
            continue
        k = str(eid)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(e)
    return deduped


def _match_team_name_local(
    nom_equipe_rencontre: str,
    organisme_nom: str,
    numero_equipe: int | None,
    is_organisme_nom_normalized: bool = False,
) -> bool:
    from .common import _NUMERIC_EXTRACT_PATTERN

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
    has_trailing = (
        nom_norm.endswith(f"- {str_num}")
        or nom_norm.endswith(f" {str_num}")
        or nom_norm.endswith(f"-{str_num}")
        or nom_norm.endswith(f"_{str_num}")
    )
    if search_num == 1:
        has_digit = bool(_NUMERIC_EXTRACT_PATTERN.search(nom_norm))
        return has_trailing or not has_digit
    return has_trailing


async def _build_calendar_matches(
    club_name: str | None,
    organisme_id: int | str | None,
    categorie: str | None,
    numero_equipe: int | None,
    adversaire: str | None,
    date_debut: str | None,
    date_fin: str | None,
    limit: int | None,
    engagement_id: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    season_id: int | str | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Construit la liste des matchs (calendrier complet) pour un club / catégorie."""
    from .search import resolve_club_and_org

    resolved_clubs, _ = await resolve_club_and_org(
        club_name=club_name, organisme_id=organisme_id, categorie=categorie, limit=5
    )

    if not resolved_clubs:
        return {
            "items": [],
            "_meta": {
                "total": 0,
                "returned": 0,
                "limit": limit if limit is not None else 0,
                "offset": offset if offset is not None else 0,
                "has_more": False,
                "sort": "scheduled_at:asc",
                "generated_at": datetime.now(_TZ).isoformat(),
            },
            "error": (
                f"Aucun club trouvé pour '{club_name or organisme_id}'. "
                "Vérifie l'orthographe ou utilise ffbb_search."
            ),
        }

    from .common import (
        disambiguate_clubs_by_category,
        get_primary_club,
        is_real_ambiguity,
    )

    if not organisme_id and categorie:
        resolved_clubs, _ = await disambiguate_clubs_by_category(
            resolved_clubs,
            categorie=categorie,
            club_name=club_name,
            season_id=season_id,
        )

    if is_real_ambiguity(resolved_clubs, club_name) and not organisme_id:
        candidates = [
            {
                "id": str(c.get("organisme_id"))
                if c.get("organisme_id") is not None
                else None,
                "nom": c.get("nom"),
                "ville": c.get("ville"),
            }
            for c in resolved_clubs
            if isinstance(c, dict)
        ]
        return {
            "items": [],
            "_meta": {
                "total": 0,
                "returned": 0,
                "limit": limit if limit is not None else 0,
                "offset": offset if offset is not None else 0,
                "has_more": False,
                "sort": "scheduled_at:asc",
                "generated_at": datetime.now(_TZ).isoformat(),
            },
            "error": (
                f"Plusieurs clubs correspondent à '{club_name}'. "
                "Précise l'organisme_id ou un nom plus exact."
            ),
            "candidates": candidates,
        }

    target_org_ids = [str(c["organisme_id"]) for c in resolved_clubs]
    target_org_ids = list(dict.fromkeys(oid for oid in target_org_ids if oid))

    primary_c = get_primary_club(resolved_clubs, club_name)
    club_nom_resolu = (
        primary_c.get("nom", "")
        if primary_c
        else (resolved_clubs[0].get("nom", "") if resolved_clubs else "")
    )
    import ffbb_mcp.services as svc

    eq_tasks = [
        svc.ffbb_equipes_club_service(
            organisme_id=oid, filtre=categorie, season_id=season_id
        )
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
        return {
            "items": [],
            "_meta": {
                "total": 0,
                "returned": 0,
                "limit": limit if limit is not None else 0,
                "offset": offset if offset is not None else 0,
                "has_more": False,
                "sort": "scheduled_at:asc",
                "generated_at": datetime.now(_TZ).isoformat(),
            },
            "warning": (
                f"Aucune équipe active pour '{club_name or organisme_id}' "
                f"(catégorie: '{categorie or 'toutes'}'). "
                "Le club existe mais n'a pas d'équipes engagées."
            ),
        }

    if engagement_id is not None:
        target_eng = str(engagement_id).strip()
        equipes = [
            e
            for e in equipes
            if str(e.get("engagement_id") or e.get("team_id") or "").strip()
            == target_eng
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
    if not equipes:
        return {
            "items": [],
            "_meta": {
                "total": 0,
                "returned": 0,
                "limit": limit or 0,
                "offset": offset or 0,
                "sort": "scheduled_at:asc",
                "has_more": False,
                "generated_at": datetime.now(_TZ).isoformat(),
            },
            "warning": (
                f"Aucun engagement ne correspond aux critères de compétition spécifiés "
                f"(engagement_id={engagement_id}, competition_id={competition_id}, competition_type={competition_type})."
            ),
        }

    equipes = _dedup_equipes_by_engagement_local(equipes)

    seen_match_ids: set[Any] = set()
    all_matches: list[dict[str, Any]] = []

    unique_poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )

    import unittest.mock

    from .poule import get_poule_service as poule_fn

    if isinstance(
        getattr(svc, "get_poule_service", None),
        (unittest.mock.AsyncMock, unittest.mock.MagicMock),
    ):
        poule_getter = svc.get_poule_service
    else:
        poule_getter = poule_fn

    poule_tasks = [poule_getter(poule_id) for poule_id in unique_poule_ids]
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

        equipe_eng_id = str(
            equipe.get("engagement_id")
            or equipe.get("team_id")
            or equipe.get("id")
            or ""
        )
        eq_num = None
        raw_eq_num = equipe.get("numero_equipe")
        try:
            eq_num = int(raw_eq_num) if raw_eq_num is not None else numero_equipe
        except (ValueError, TypeError):
            eq_num = numero_equipe

        for match in poule_data.get("rencontres") or []:
            if not isinstance(match, dict):
                continue
            match_id = match.get("id")
            if match_id is None or match_id == "" or match_id in seen_match_ids:
                continue

            eng1 = match.get("idEngagementEquipe1")
            eng2 = match.get("idEngagementEquipe2")
            id_eng1 = str(eng1.get("id") if isinstance(eng1, dict) else (eng1 or ""))
            id_eng2 = str(eng2.get("id") if isinstance(eng2, dict) else (eng2 or ""))

            num1 = _engagement_numero(eng1)
            num2 = _engagement_numero(eng2)

            raw_nom1 = match.get("nomEquipe1", match.get("nom_equipe1", ""))
            raw_nom2 = match.get("nomEquipe2", match.get("nom_equipe2", ""))
            eq1 = format_team_name(raw_nom1, num1)
            eq2 = format_team_name(raw_nom2, num2)

            is_our_match = False
            if equipe_eng_id and equipe_eng_id in (id_eng1, id_eng2):
                is_our_match = True
            elif club_nom_resolu:
                org_nom_norm = _normalize_name(club_nom_resolu)
                is_our_match = _match_team_name_local(
                    str(raw_nom1),
                    org_nom_norm,
                    eq_num,
                    is_organisme_nom_normalized=True,
                ) or _match_team_name_local(
                    str(raw_nom2),
                    org_nom_norm,
                    eq_num,
                    is_organisme_nom_normalized=True,
                )

            if not is_our_match:
                equipe_nom = str(
                    equipe.get("nom_equipe") or equipe.get("team_label") or ""
                )
                if equipe_nom:
                    eq_nom_norm = _normalize_name(equipe_nom)
                    raw1_norm = _normalize_name(str(raw_nom1))
                    raw2_norm = _normalize_name(str(raw_nom2))
                    if (
                        (
                            eq_nom_norm
                            and (eq_nom_norm in raw1_norm or eq_nom_norm in raw2_norm)
                        )
                        or (raw1_norm and raw1_norm in eq_nom_norm)
                        or (raw2_norm and raw2_norm in eq_nom_norm)
                    ):
                        is_our_match = True
                elif not equipe_eng_id and not club_nom_resolu:
                    is_our_match = True

            if not is_our_match:
                continue

            seen_match_ids.add(match_id)

            score1 = match.get("resultatEquipe1", match.get("resultat_equipe1"))
            score2 = match.get("resultatEquipe2", match.get("resultat_equipe2"))
            date_match = match.get("date_rencontre", match.get("date", ""))
            journee = match.get("numeroJournee", match.get("numero_journee", ""))
            joue = match.get("joue")
            salle = match.get("salle") or match.get("idSalle") or match.get("id_salle")
            dt_parsed = _parse_dt(date_match)
            time_confirmed = bool(_is_horaire_renseigne(match, dt_parsed))
            if dt_parsed is not None:
                scheduled_date = dt_parsed.strftime("%Y-%m-%d")
                scheduled_at = dt_parsed.isoformat() if time_confirmed else None
                iso_date = dt_parsed.isoformat() if time_confirmed else scheduled_date
            else:
                raw_str = str(date_match or "")
                scheduled_date = raw_str[:10] if len(raw_str) >= 10 else (raw_str or "")
                scheduled_at = None
                iso_date = scheduled_date or None  # type: ignore[assignment]
                time_confirmed = False

            calendar_match: dict[str, Any] = {
                "id": str(match_id),
                "date": iso_date,
                "scheduled_date": scheduled_date,
                "scheduled_at": scheduled_at,
                "time_confirmed": time_confirmed,
                "horaire_renseigne": time_confirmed,
                "statut": _compute_match_statut(match, dt_parsed),
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
                calendar_match["salle"] = (
                    str(salle) if not isinstance(salle, dict) else salle
                )
            all_matches.append(calendar_match)

    # Enrichissement bulk des salle_ids
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
                    except (httpx.HTTPError, ValidationError):
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
            except (AttributeError, TypeError):
                pass

    # Salle details bulk
    from .salle import _enrich_matches_with_salle_details as _enrich

    await _enrich(all_matches)

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
            m["nom_salle"] = sd.get("libelle") or ""
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

    tz = _TZ
    now = datetime.now(tz)

    for m in all_matches:
        m["_dt"] = _parse_dt(m.get("date"))

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

    if adversaire:
        adversaire_norm = _normalize_name(adversaire)
        club_norm = _normalize_name(club_nom_resolu)
        all_matches = [
            m
            for m in all_matches
            if (
                club_norm in _normalize_name(m.get("equipe1", ""))
                and adversaire_norm in _normalize_name(m.get("equipe2", ""))
            )
            or (
                club_norm in _normalize_name(m.get("equipe2", ""))
                and adversaire_norm in _normalize_name(m.get("equipe1", ""))
            )
        ]

    all_matches.sort(key=lambda x: (x["_dt"] is None, x["_dt"] or now))

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
    total_before_limit = len(effective)

    effective_offset = max(0, offset) if offset is not None else 0
    if limit is not None:
        limit = max(1, min(100, limit))
        applied_limit: int | None = limit
        paginated = effective[effective_offset : effective_offset + limit]
    elif len(effective) > max_matches:
        applied_limit = max_matches
        if offset is not None:
            paginated = effective[effective_offset : effective_offset + max_matches]
        else:
            paginated = effective[:max_matches]
            effective_offset = 0
    else:
        applied_limit = limit
        if offset is not None:
            paginated = effective[effective_offset : effective_offset + (limit or 100)]
            if limit is None:
                applied_limit = 100
        else:
            paginated = effective
            effective_offset = 0
            if limit is None:
                applied_limit = None

    if offset is not None and effective_offset >= total_before_limit:
        paginated = []

    effective = paginated

    validated_matches = []
    for m in effective:
        if "warning" in m:
            validated_matches.append(m)
        else:
            validated_matches.append(CalendrierMatch(**m).model_dump(by_alias=True))

    has_more = (effective_offset + len(validated_matches)) < total_before_limit
    next_offset = (effective_offset + len(validated_matches)) if has_more else None
    meta: dict[str, Any] = {
        "total": total_before_limit,
        "returned": len(validated_matches),
        "limit": applied_limit
        if applied_limit is not None
        else (limit or total_before_limit),
        "offset": effective_offset,
        "has_more": has_more,
        "sort": "scheduled_at:asc",
        "generated_at": datetime.now(tz).isoformat(),
    }
    if next_offset is not None:
        meta["next_offset"] = next_offset
    if has_more:
        meta["truncated"] = True

    return {
        "items": validated_matches,
        "_meta": meta,
    }


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
    offset: int | None = None,
    engagement_id: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    season_id: int | str | None = None,
    force_refresh: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    if engagement_id is None:
        engagement_id = kwargs.get("engagement_id")
    if offset is None:
        offset = kwargs.get("offset")
    limit = max(1, min(100, limit)) if limit is not None else None
    if offset is not None:
        offset = max(0, offset)
    # Clé de cache sans limit/offset pour maximiser le hit ratio.
    # La pagination est appliquée en aval sur le résultat complet.
    cache_key = f"calendrier:{organisme_id or ''}:{_normalize_name(club_name or '')}:{_normalize_name(categorie or '')}:{numero_equipe or ''}:{_normalize_name(adversaire or '')}:{date_debut or ''}:{date_fin or ''}:{engagement_id or ''}:{competition_id or ''}:{competition_type or ''}"

    if force_refresh and state.cache_calendrier is not None:
        state.cache_calendrier.pop(cache_key, None)

    from .common import _dedupe_inflight as _dedupe

    return await _dedupe(
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
            engagement_id=engagement_id,
            competition_id=competition_id,
            competition_type=competition_type,
            season_id=season_id,
            offset=offset,
        ),
        cache_name="calendrier",
    )
