from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from .club import ffbb_equipes_club_service, get_calendrier_club_service
from .poule import get_organisme_service, get_poule_service

logger = logging.getLogger("ffbb-mcp")


async def warmup_cache_service(
    organisme_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Préchauffe proactivement les caches (organisme, équipes, poules, calendriers) pour une liste d'organismes."""
    if organisme_ids is None:
        env_orgs = os.environ.get("FFBB_WARMUP_ORGANISMES", "")
        if env_orgs:
            organisme_ids = [
                org_id.strip() for org_id in env_orgs.split(",") if org_id.strip()
            ]
        else:
            organisme_ids = []

    if not organisme_ids:
        return {
            "status": "skipped",
            "message": "Aucun organisme à préchauffer. Configurez la liste via le paramètre ou la variable d'environnement FFBB_WARMUP_ORGANISMES.",
            "details": {
                "organismes_demandes": 0,
                "organismes_prechauffes": 0,
                "calendriers_prechauffes": 0,
                "poules_detectees": 0,
                "poules_prechauffees": 0,
            },
        }

    logger.info("Début du préchauffage du cache pour les organismes: %s", organisme_ids)

    # 1. Préchauffer les détails des organismes en parallèle
    org_results = await asyncio.gather(
        *[get_organisme_service(org_id) for org_id in organisme_ids],
        return_exceptions=True,
    )

    # 2. Préchauffer les équipes et calendriers de chaque organisme
    cal_tasks = []
    eq_tasks = []
    for org_id in organisme_ids:
        cal_tasks.append(get_calendrier_club_service(organisme_id=org_id))
        eq_tasks.append(ffbb_equipes_club_service(organisme_id=org_id))

    cal_results = await asyncio.gather(*cal_tasks, return_exceptions=True)
    eq_results = await asyncio.gather(*eq_tasks, return_exceptions=True)

    # 3. Récupérer toutes les poules uniques à partir des équipes
    poule_ids = set()
    for eq_list in eq_results:
        if isinstance(eq_list, list):
            for eq in eq_list:
                if isinstance(eq, dict) and eq.get("poule_id"):
                    poule_ids.add(str(eq["poule_id"]))

    logger.info("Poules uniques détectées pour préchauffage : %s", list(poule_ids))

    # 4. Préchauffer toutes les poules en parallèle
    poule_results = []
    if poule_ids:
        poule_results = await asyncio.gather(
            *[get_poule_service(pid) for pid in poule_ids],
            return_exceptions=True,
        )

    org_success = sum(1 for r in org_results if isinstance(r, dict) and r)
    cal_success = sum(
        1 for r in cal_results if isinstance(r, list) and r and "error" not in r[0]
    )
    poule_success = sum(1 for r in poule_results if isinstance(r, dict) and r)

    logger.info(
        "Préchauffage du cache terminé avec succès. Organismes: %d/%d, Calendriers: %d/%d, Poules: %d/%d",
        org_success,
        len(organisme_ids),
        cal_success,
        len(organisme_ids),
        poule_success,
        len(poule_ids),
    )

    return {
        "status": "completed",
        "details": {
            "organismes_demandes": len(organisme_ids),
            "organismes_prechauffes": org_success,
            "calendriers_prechauffes": cal_success,
            "poules_detectees": len(poule_ids),
            "poules_prechauffees": poule_success,
        },
    }
