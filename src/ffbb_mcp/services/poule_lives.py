"""Module de gestion des scores et matchs en direct (Lives FFBB).

Extrait de services/poule.py pour isoler la logique de polling,
de classification d'état de match live et de fallback calendrier.
"""

from __future__ import annotations

import logging
from typing import Any

from ffbb_mcp._state import state
from ffbb_mcp.cache_strategy import get_static_ttl
from ffbb_mcp.client import get_client_async
from ffbb_mcp.utils import serialize_model

from .common import (
    _cache_set,
    _normalize_name,
    _read_positive_int_env,
    _safe_call_with_inflight,
    _swr_serve,
    _with_ffbb_semaphore,
)

logger = logging.getLogger("ffbb-mcp")


async def _fetch_lives() -> list[dict]:
    import sys

    poule_mod = sys.modules.get("ffbb_mcp.services.poule")
    client_getter = getattr(poule_mod, "get_client_async", get_client_async)
    client = await client_getter()
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
    import sys

    poule_mod = sys.modules.get("ffbb_mcp.services.poule")
    fetch_fn = getattr(poule_mod, "_fetch_lives", _fetch_lives)
    ttl = _read_positive_int_env("FFBB_CACHE_TTL_LIVES", get_static_ttl("lives"))
    raw_lives = await _swr_serve(state.cache_lives, "lives", "lives", ttl, fetch_fn)
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
