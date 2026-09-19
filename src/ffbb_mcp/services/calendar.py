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
from datetime import datetime, timedelta
from typing import Any

import httpx
from pydantic import ValidationError

from ffbb_mcp._state import state
from ffbb_mcp.models import CalendrierMatch
from ffbb_mcp.utils import format_team_name

from .common import _PARIS_TZ as _TZ
from .common import (
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
    scope: str | None = None,
    include_competition_types: list[str] | None = None,
    exclude_competition_types: list[str] | None = None,
    include_friendlies: bool = False,
    include_youth: bool = False,
    include_reserves: bool = False,
    status_filter: list[str] | None = None,
    strict_filters: bool = True,
    group_by: str | None = None,
    **kwargs: Any,
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
    import sys

    import ffbb_mcp.services as svc

    from .club import ffbb_equipes_club_service as default_eq_svc

    eq_svc = (
        getattr(sys.modules[__name__], "ffbb_equipes_club_service", None)
        or getattr(svc, "ffbb_equipes_club_service", None)
        or default_eq_svc
    )

    eq_tasks = [
        eq_svc(organisme_id=oid, filtre=categorie, season_id=season_id)
        for oid in target_org_ids
    ]
    eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

    equipes: list[dict[str, Any]] = []
    for res in eq_results:
        if isinstance(res, list):
            equipes.extend([e for e in res if isinstance(e, dict) and "error" not in e])
        elif isinstance(res, Exception):
            logger.error("Erreur lors de la récupération des équipes: %s", res)

    all_teams_raw = list(equipes)

    if not all_teams_raw:
        return {
            "status": "not_found",
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
                f"Aucune équipe active pour '{club_nom_resolu or club_name or organisme_id}' "
                f"(catégorie: '{categorie or 'toutes'}'). "
                "Le club existe mais n'a pas d'équipes engagées."
            ),
            "candidates": [],
        }

    effective_scope = scope
    if not effective_scope:
        if categorie or numero_equipe is not None or engagement_id is not None:
            effective_scope = "team"
        elif competition_id is not None:
            effective_scope = "competition"
        else:
            effective_scope = "club"

    from ffbb_mcp.aliases_registry import get_aliases_registry
    from ffbb_mcp.utils import parse_categorie

    registry = get_aliases_registry()
    target_div = registry.lookup(categorie) if categorie else None

    if effective_scope in ("team", "competition"):
        if target_div:
            equipes = [
                e
                for e in equipes
                if registry.is_compatible(
                    categorie, e.get("competition_code"), e.get("competition")
                )
                or registry.is_compatible(
                    categorie, e.get("categorie"), e.get("nom") or e.get("team_label")
                )
            ]
        elif categorie:
            parsed_c = parse_categorie(categorie)
            if parsed_c and parsed_c.categorie:
                req_c = parsed_c.categorie.upper().strip()
                equipes = [
                    e
                    for e in equipes
                    if (e.get("categorie") or "").upper().strip() == req_c
                    or {(e.get("categorie") or "").upper().strip(), req_c}
                    <= {"SE", "SENIOR", "SENIORS"}
                ]
                if parsed_c.sexe:
                    equipes = [
                        e
                        for e in equipes
                        if (e.get("sexe") or "").upper().strip() == parsed_c.sexe
                    ]

        if numero_equipe is not None:
            num_str = str(numero_equipe).strip()
            equipes_filtrees = [
                e
                for e in equipes
                if str(e.get("numero_equipe") or "").strip() == num_str
                or str(e.get("nom") or "").endswith(f"- {num_str}")
            ]
            if not equipes_filtrees and numero_equipe == 1:
                equipes_filtrees = [
                    e for e in equipes if not str(e.get("numero_equipe") or "").strip()
                ]
            equipes = equipes_filtrees
        elif target_div and not include_reserves:
            equipes = [
                e
                for e in equipes
                if str(e.get("numero_equipe") or "").strip() in ("1", "")
            ]

        # Exclusion des amicaux par défaut
        if not include_friendlies:
            equipes = [
                e
                for e in equipes
                if str(e.get("competition_type") or "").upper()
                not in ("PLAT", "AMIC", "AMICAL")
                and "AMIC" not in str(e.get("competition") or "").upper()
                and "TOURNVOI" not in str(e.get("competition") or "").upper()
                and "TOURNOI" not in str(e.get("competition") or "").upper()
            ]

        # Exclusion des coupes par défaut si une division de championnat est ciblée
        if include_competition_types:
            inc_types = {t.upper() for t in include_competition_types}
            equipes = [
                e
                for e in equipes
                if str(e.get("competition_type") or "").upper() in inc_types
            ]
        elif target_div and not kwargs.get("include_cup", False):
            equipes = [
                e
                for e in equipes
                if str(e.get("competition_type") or "").upper() != "COUPE"
                and "COUPE" not in str(e.get("competition") or "").upper()
            ]

        if exclude_competition_types:
            exc_types = {t.upper() for t in exclude_competition_types}
            equipes = [
                e
                for e in equipes
                if str(e.get("competition_type") or "").upper() not in exc_types
            ]

        # Exclusion espoirs si senior demandé
        if target_div and not target_div.is_espoir:
            equipes = [
                e
                for e in equipes
                if "ESPOIR" not in str(e.get("competition") or "").upper()
            ]

        # Exclusion équipes jeunes si senior demandé
        if not include_youth and target_div and target_div.is_senior:
            equipes = [
                e
                for e in equipes
                if (e.get("categorie") or "").upper().strip()
                in ("SE", "SENIOR", "SENIORS")
                or not (e.get("categorie") or "").upper().strip().startswith("U")
            ]

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
        all_labels = sorted(
            [str(t["team_label"]) for t in all_teams_raw if t.get("team_label")]
        )
        return {
            "status": "not_found",
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
                f"Aucun engagement ne correspond aux critères spécifiés (catégorie='{categorie}', scope='{effective_scope}'). "
                "Aucun élargissement silencieux au calendrier global du club n'est autorisé."
            ),
            "candidates": all_labels,
        }

    equipes = _dedup_equipes_by_engagement_local(equipes)

    seen_match_ids: set[Any] = set()
    all_matches: list[dict[str, Any]] = []

    unique_poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )

    import sys
    import unittest.mock

    from .poule import get_poule_service as poule_fn

    poule_mod = sys.modules.get("ffbb_mcp.services.poule")
    poule_getter = None
    for cand in [
        getattr(poule_mod, "get_poule_service", None),
        getattr(svc, "get_poule_service", None),
    ]:
        if isinstance(
            cand, (unittest.mock.AsyncMock, unittest.mock.MagicMock)
        ) or hasattr(cand, "mock_calls"):
            poule_getter = cand
            break
    if poule_getter is None:
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

            from ffbb_mcp.canonical_status import (
                CanonicalMatchStatus,
                canonicalize_match_status,
            )

            canon_statut, data_quality = canonicalize_match_status(match)

            # Exclure les matchs en conflit sauf demande explicite
            if canon_statut == CanonicalMatchStatus.UNKNOWN_CONFLICT and not kwargs.get(
                "include_conflicts", False
            ):
                continue

            # Exclure les matchs annulés sauf demande explicite
            if canon_statut == CanonicalMatchStatus.CANCELLED and not kwargs.get(
                "include_cancelled", False
            ):
                continue

            if status_filter:
                clean_sf = [s.lower() for s in status_filter]
                if canon_statut.value not in clean_sf:
                    continue

            calendar_match: dict[str, Any] = {
                "id": str(match_id),
                "date": iso_date,
                "scheduled_date": scheduled_date,
                "scheduled_at": scheduled_at,
                "time_confirmed": time_confirmed,
                "horaire_renseigne": time_confirmed,
                "statut": canon_statut.value,
                "canonical_status": canon_statut.value,
                "data_quality": data_quality.model_dump(),
                "joue": joue,
                "equipe1": eq1,
                "equipe2": eq2,
                "score_equipe1": score1,
                "score_equipe2": score2,
                "engagement_id": equipe_eng_id,
                "team_label": equipe.get("team_label")
                or equipe.get("nom_equipe")
                or "",
                "numero_equipe": eq_num,
                "competition_id": str(equipe.get("competition_id") or ""),
                "competition_name": equipe.get("competition", ""),
                "competition_nom": equipe.get("competition", ""),
                "competition_type": equipe.get("competition_type")
                or _detect_phase_type(equipe.get("competition", "")),
                "poule_id": str(poule_id),
                "season_id": str(season_id or equipe.get("season_id") or ""),
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
        dt_val = m.get("_dt")
        has_scores = (
            m.get("score_equipe1") is not None
            and m.get("score_equipe2") is not None
            and str(m.get("score_equipe1")).strip() not in ("", "None", "null")
            and str(m.get("score_equipe2")).strip() not in ("", "None", "null")
        )
        is_past = dt_val is not None and dt_val < (now - timedelta(hours=3))
        is_final_statut = m.get("statut") in ("final", "official", "forfeit")

        m["played"] = bool(
            m.get("joue") in (1, "1", True) or has_scores or is_final_statut or is_past
        )
        if m["played"]:
            played_indices.append(idx)
        else:
            future_indices.append(idx)

    last_played_idx = played_indices[-1] if played_indices else None
    next_future_idx = future_indices[0] if future_indices else None

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
    scope: str | None = None,
    include_competition_types: list[str] | None = None,
    exclude_competition_types: list[str] | None = None,
    include_friendlies: bool = False,
    include_youth: bool = False,
    include_reserves: bool = False,
    status_filter: list[str] | None = None,
    strict_filters: bool = True,
    group_by: str | None = None,
    force_refresh: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    if engagement_id is None:
        engagement_id = kwargs.get("engagement_id")
    if offset is None:
        offset = kwargs.get("offset")
    if scope is None:
        scope = kwargs.get("scope")
    if include_competition_types is None:
        include_competition_types = kwargs.get("include_competition_types")
    if exclude_competition_types is None:
        exclude_competition_types = kwargs.get("exclude_competition_types")
    if status_filter is None:
        status_filter = kwargs.get("status_filter")
    if group_by is None:
        group_by = kwargs.get("group_by")

    limit = max(1, min(100, limit)) if limit is not None else None
    if offset is not None:
        offset = max(0, offset)

    inc_types = ",".join(sorted(include_competition_types or []))
    exc_types = ",".join(sorted(exclude_competition_types or []))
    st_filter = ",".join(sorted(status_filter or []))
    # Clé de cache incluant le scope et les filtres métier
    cache_key = (
        f"calendrier:{organisme_id or ''}:{_normalize_name(club_name or '')}:"
        f"{_normalize_name(categorie or '')}:{numero_equipe or ''}:"
        f"{_normalize_name(adversaire or '')}:{date_debut or ''}:{date_fin or ''}:"
        f"{engagement_id or ''}:{competition_id or ''}:{competition_type or ''}:"
        f"{scope or ''}:{inc_types}:{exc_types}:{include_friendlies}:{include_youth}:"
        f"{include_reserves}:{st_filter}:{strict_filters}:{group_by or ''}:{season_id or ''}"
    )

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
            scope=scope,
            include_competition_types=include_competition_types,
            exclude_competition_types=exclude_competition_types,
            include_friendlies=include_friendlies,
            include_youth=include_youth,
            include_reserves=include_reserves,
            status_filter=status_filter,
            strict_filters=strict_filters,
            group_by=group_by,
        ),
        cache_name="calendrier",
    )
