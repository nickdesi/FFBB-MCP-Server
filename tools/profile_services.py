import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from ffbb_mcp import services
from ffbb_mcp.services import ffbb_bilan_service, get_calendrier_club_service

# Build reusable mocks similar to tests


def make_org_mock():
    m = MagicMock()
    m.model_dump = MagicMock(
        return_value={
            "id": "9326",
            "nom": "SCBA",
            "engagements": [
                {
                    "id": "eng1",
                    "numeroEquipe": "1",
                    "idCompetition": {
                        "nom": "Dépt U11M Phase 1",
                        "id": "c1",
                        "sexe": "M",
                        "categorie": {"code": "u11"},
                        "competition_origine_niveau": 1,
                    },
                    "idPoule": {"id": "p1"},
                },
                {
                    "id": "eng2",
                    "numeroEquipe": "1",
                    "idCompetition": {
                        "nom": "Dépt U11M Phase 2",
                        "id": "c2",
                        "sexe": "M",
                        "categorie": {"code": "u11"},
                        "competition_origine_niveau": 2,
                    },
                    "idPoule": {"id": "p2"},
                },
            ],
        }
    )
    return m


def make_poule_mock(poule_id, engagement_id, gagnes, perdus, pm, pe):
    m = MagicMock()
    m.model_dump = MagicMock(
        return_value={
            "id": poule_id,
            "rencontres": [],
            "classements": [
                {
                    "id_engagement": {"id": engagement_id, "numero_equipe": "1"},
                    "organisme_id": "9326",
                    "position": 1,
                    "match_joues": gagnes + perdus,
                    "gagnes": gagnes,
                    "perdus": perdus,
                    "nuls": 0,
                    "paniers_marques": pm,
                    "paniers_encaisses": pe,
                    "difference": pm - pe,
                }
            ],
        }
    )
    return m


async def workload(iterations: int = 20):
    # Prepare mocks and patch service-level get_client_async to use them
    client = MagicMock()
    org_mock = make_org_mock()
    poule1 = make_poule_mock("p1", "eng1", 3, 0, 150, 40)
    poule2 = make_poule_mock("p2", "eng2", 6, 0, 300, 100)

    client.get_organisme_async = AsyncMock(return_value=org_mock)

    async def get_poule_async_side_effect(poule_id=None):
        if str(poule_id) == "p1":
            return poule1
        if str(poule_id) == "p2":
            return poule2
        return None

    client.get_poule_async = AsyncMock(side_effect=get_poule_async_side_effect)

    # Patch the module-level get_client_async used by services
    services.get_client_async = AsyncMock(return_value=client)
    # Ensure caches and inflight maps are cleared so each call exercises
    # the full code path instead of returning cached results.
    try:
        services._cache_detail.clear()

        services._inflight_detail.clear()

    except Exception:
        pass

    # Warmup
    await ffbb_bilan_service(organisme_id=9326, categorie="U11M1")
    await get_calendrier_club_service(organisme_id=9326, categorie="U11M1")

    # Timed workload
    start = time.perf_counter()
    for _ in range(iterations):
        await ffbb_bilan_service(organisme_id=9326, categorie="U11M1")
        await get_calendrier_club_service(organisme_id=9326, categorie="U11M1")
    end = time.perf_counter()
    print(
        f"Workload completed: {iterations} iterations, total={end - start:.3f}s, avg per iteration={(end - start) / iterations:.4f}s"
    )


if __name__ == "__main__":
    asyncio.run(workload(20))
