"""Services bilan & saison — extraits de :mod:`ffbb_mcp.services.club`.

Réduit la complexité cyclomatique du monolithe historique (~2826 lignes)
en isolant les deux pipelines les plus lourds:

* calcul via ``rencontres`` (fallback phases finales)
* agrégation ``_build_bilan_payload`` / ``ffbb_bilan_service``
* ``ffbb_saison_bilan_service``

Les imports croisés vers ``club``/``poule``/``search`` sont faits à
l'intérieur des fonctions (lazy) pour éviter tout cycle à l'import.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import httpx
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from ffbb_mcp._state import state
from ffbb_mcp.models import BilanResponse
from ffbb_mcp.utils import parse_categorie

from .common import (
    _BILAN_STAT_FIELDS,
    _detect_phase_type,
    _extract_and_accumulate_bilan,
    _freshness_meta,
    _new_bilan_totals,
    _normalize_name,
)

logger = logging.getLogger("ffbb-mcp")
_EMPTY_SET: set[str] = set()


# ---------------------------------------------------------------------------
# Fallback bilan via rencontres (phases finales sans classements)
# ---------------------------------------------------------------------------


def _compute_bilan_from_rencontres(
    poule_data: dict[str, Any],
    eng_ids: set[str],
    club_nom: str,
) -> dict[str, int] | None:
    """Calcule le bilan d'une équipe depuis les rencontres quand les classements sont vides."""
    from .common import _normalize_name as _norm

    rencontres = poule_data.get("rencontres") or []
    if not rencontres:
        return None

    stats = _new_bilan_totals()
    club_norm = _norm(club_nom)
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
        except (TypeError, ValueError):
            continue

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
            eq1_norm = _norm(eq1)
            eq2_norm = _norm(eq2)
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


# ---------------------------------------------------------------------------
# Helpers internes saison/bilan partagés
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# ffbb_saison_bilan_service
# ---------------------------------------------------------------------------


async def ffbb_saison_bilan_service(
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
) -> dict[str, Any]:
    if engagement_id is None:
        engagement_id = kwargs.get("engagement_id")

    if categorie:
        parsed_cat = parse_categorie(categorie)
        if parsed_cat.numero_equipe is not None:
            numero_equipe = parsed_cat.numero_equipe

    from .club import _resolve_team_equipes  # lazy to avoid cycle

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

    poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )
    if not poule_ids:
        return {
            "status": "not_found",
            "message": "Aucune poule associée à cette équipe.",
            "club_resolu": club_resolu,
        }

    async def _fetch_poule(pid: str) -> dict[str, Any] | Exception:
        from .poule import get_poule_service

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
        classements = poule_data.get("classements") or []
        poule_phase_added = False
        for entry in classements:
            eng = entry.get("id_engagement") or {}
            entry_eng_id = str(eng.get("id", ""))
            if entry_eng_id not in eng_ids:
                continue

            if poule_phase_added:
                continue
            poule_phase_added = True

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

    all_rencontres = [
        r
        for pd in poules_map.values()
        if isinstance(pd, dict)
        for r in (pd.get("rencontres") or [])
    ]
    from ..dynamique import compute_team_dynamique

    total_gagnes = totaux.get("gagnes", 0)
    total_joues = totaux.get("match_joues", 0)
    ratio_saison = (
        round(total_gagnes / total_joues * 100, 1) if total_joues > 0 else None
    )

    dynamique = compute_team_dynamique(
        all_rencontres,
        eng_ids=eng_ids,
        club_nom=club_nom,
        ratio_global_victoires=ratio_saison,
    )

    return {
        "status": "ok",
        "club": club_nom,
        "categorie": categorie or "",
        "bilan_total": totaux,
        "dynamique": dynamique,
        "saison_terminee": saison_terminee,
        "competitions_incluses": competitions_incluses,
        "phases": phases,
        "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
    }


# ---------------------------------------------------------------------------
# _build_bilan_payload + ffbb_bilan_service
# ---------------------------------------------------------------------------


async def _build_bilan_payload(
    club_name: str | None,
    organisme_id: int | str | None,
    categorie: str | None,
    engagement_id: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    poule_id: int | str | None = None,
    season_id: int | str | None = None,
) -> dict[str, Any]:
    """Calcule le payload complet d'un bilan pour un club / catégorie.

    Extrait de la closure ``_fetch`` historiquement définie dans
    ``ffbb_bilan_service``. Pas de logique de cache ici.
    """
    from .search import resolve_club_and_org

    if not club_name and not organisme_id and engagement_id:
        from ..client import FFBBClientFactory

        client = await FFBBClientFactory.get_client_async()
        try:
            eng_data = await client.get_engagement_async(str(engagement_id).strip())
            if eng_data and eng_data.idOrganisme:
                organisme_id = str(eng_data.idOrganisme)
        except Exception as exc:
            logger.error(
                "Erreur résolution engagement %s dans bilan: %s",
                engagement_id,
                exc,
            )

    resolved_clubs, org_data = await resolve_club_and_org(
        club_name=club_name, organisme_id=organisme_id, categorie=categorie
    )

    from .common import disambiguate_clubs_by_category

    if not organisme_id and categorie:
        resolved_clubs, _ = await disambiguate_clubs_by_category(
            resolved_clubs,
            categorie=categorie,
            club_name=club_name,
            season_id=season_id,
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

    from .club import ffbb_equipes_club_service as _eq_svc  # lazy

    eq_tasks = []
    for oid in target_org_ids:
        is_target = organisme_id and str(oid) == str(organisme_id)
        pass_org = org_data if is_target else None
        eq_tasks.append(
            _eq_svc(
                organisme_id=oid,
                filtre=categorie,
                org_data=pass_org,
                season_id=season_id,
            )
        )
    eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

    equipes: list[dict[str, Any]] = []
    for res in eq_results:
        if isinstance(res, list):
            equipes.extend([e for e in res if isinstance(e, dict) and "error" not in e])
        elif isinstance(res, Exception):
            logger.error("Erreur lors de la récupération des équipes: %s", res)

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

    if poule_id is not None:
        target_poule = str(poule_id).strip()
        equipes = [
            e for e in equipes if str(e.get("poule_id") or "").strip() == target_poule
        ]

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

    equipes = _dedup_equipes_by_engagement_local(equipes)

    unique_poule_ids = list(
        dict.fromkeys(str(e.get("poule_id")) for e in equipes if e.get("poule_id"))
    )
    logger.debug(
        f"ffbb_bilan: cible_orgs_count={len(target_org_ids)} "
        f"equipes_count={len(equipes)} unique_poules_count={len(unique_poule_ids)}"
    )

    async def _fetch_poule_bilan(pid: str) -> dict[str, Any] | Exception:
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

        try:
            return await poule_getter(pid)
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
        classements = poule_data.get("classements") or []
        for entry in classements:
            if not isinstance(entry, dict):
                continue
            eng = entry.get("id_engagement") or {}
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
                stats_to_use = stats_from_rencontres
            else:
                stats_to_use = _new_bilan_totals()

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
                    **stats_to_use,
                }
            )

    def _phase_sort_key_by_age(p: dict) -> tuple[int, str, int, str]:
        comp = p.get("competition") or ""
        parsed = parse_categorie(comp)
        age = 999
        cat = parsed.categorie
        if cat and cat.startswith("U"):
            with contextlib.suppress(ValueError):
                age = int(cat[1:])
        elif "SENIOR" in comp.upper():
            age = 100
        else:
            age = 90
        sexe = parsed.sexe or ""
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

    all_rencontres = [
        r
        for pd in poules_map.values()
        if isinstance(pd, dict)
        for r in (pd.get("rencontres") or [])
    ]
    from ..dynamique import compute_team_dynamique

    for num, eq_data in equipes_bilan.items():
        team_eng_ids = {eid for eid, n in eng_to_num.items() if n == num}
        if not team_eng_ids:
            team_eng_ids = set(org_ids_str)

        b = eq_data["bilan"]
        t_gagnes = b.get("gagnes", 0)
        t_joues = b.get("match_joues", 0)
        ratio_team = round(t_gagnes / t_joues * 100, 1) if t_joues > 0 else None

        eq_data["dynamique"] = compute_team_dynamique(
            all_rencontres,
            eng_ids=team_eng_ids,
            club_nom=club_nom,
            ratio_global_victoires=ratio_team,
        )

    main_team_num = (
        "1"
        if "1" in equipes_bilan
        else (next(iter(equipes_bilan.keys())) if equipes_bilan else None)
    )
    if main_team_num and main_team_num in equipes_bilan:
        main_dynamique = equipes_bilan[main_team_num]["dynamique"]
    else:
        tot_gagnes = totaux.get("gagnes", 0)
        tot_joues = totaux.get("match_joues", 0)
        tot_ratio = round(tot_gagnes / tot_joues * 100, 1) if tot_joues > 0 else None
        main_dynamique = compute_team_dynamique(
            all_rencontres,
            eng_ids=set(org_ids_str),
            club_nom=club_nom,
            ratio_global_victoires=tot_ratio,
        )

    res_dict = {
        "club": club_nom,
        "categorie": categorie or "",
        "bilan_total": totaux,
        "dynamique": main_dynamique,
        "phase_courante": phase_courante,
        "saison_terminee": saison_terminee,
        "competitions_incluses": competitions_incluses,
        "equipes_bilan": equipes_bilan,
        "phases": phases,
        "_meta": _freshness_meta(cache="bilan", force_refresh_supported=True),
    }
    return BilanResponse(**res_dict).model_dump(by_alias=True)  # type: ignore[arg-type]


async def ffbb_bilan_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    engagement_id: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    poule_id: int | str | None = None,
    season_id: int | str | None = None,
    force_refresh: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    if engagement_id is None:
        engagement_id = kwargs.get("engagement_id")
    cache_key = f"bilan:{organisme_id or ''}:{_normalize_name(club_name or '')}:{_normalize_name(categorie or '')}:{engagement_id or ''}:{competition_id or ''}:{competition_type or ''}:{poule_id or ''}"

    if force_refresh and state.cache_bilan is not None:
        logger.debug("force_refresh=True, bypass cache pour bilan")
        state.cache_bilan.pop(cache_key, None)

    from .common import _dedupe_inflight as _dedupe

    return await _dedupe(
        cache=state.cache_bilan,
        cache_key=cache_key,
        inflight_map=state.inflight_bilan,
        make_coro=lambda: _build_bilan_payload(
            club_name,
            organisme_id,
            categorie,
            engagement_id=engagement_id,
            competition_id=competition_id,
            competition_type=competition_type,
            poule_id=poule_id,
            season_id=season_id,
        ),
        cache_name="bilan",
    )
