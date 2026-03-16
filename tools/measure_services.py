import asyncio
import os
import sys
import time
from statistics import mean, median
from unittest.mock import AsyncMock, MagicMock

from ffbb_mcp import services
from ffbb_mcp.services import ffbb_bilan_service, get_calendrier_club_service


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


async def measure(iterations: int = 100):
    client = MagicMock()
    org_mock = make_org_mock()
    poule1 = make_poule_mock("p1", "eng1", 3, 0, 150, 40)
    poule2 = make_poule_mock("p2", "eng2", 6, 0, 300, 100)

    client.get_organisme_async = AsyncMock(return_value=org_mock)

    # Optionally simulate network latency (ms) for more realistic benchmarks
    simulate_ms = int(os.environ.get("SIMULATE_LATENCY_MS", "0"))

    async def get_poule_async_side_effect(poule_id=None):
        if simulate_ms:
            await asyncio.sleep(simulate_ms / 1000.0)
        if str(poule_id) == "p1":
            return poule1
        if str(poule_id) == "p2":
            return poule2
        return None

    client.get_poule_async = AsyncMock(side_effect=get_poule_async_side_effect)

    services.get_client_async = AsyncMock(return_value=client)

    # Clear caches to measure real work
    try:
        services._cache_detail.clear()
        services._cache_bilan.clear()
        services._cache_calendrier.clear()
        services._inflight_detail.clear()
        services._inflight_bilan.clear()
        services._inflight_calendrier.clear()
    except Exception:
        pass

    # Warmup
    await ffbb_bilan_service(organisme_id=9326, categorie="U11M1")
    await get_calendrier_club_service(organisme_id=9326, categorie="U11M1")

    bilan_times = []
    calendrier_times = []

    for _i in range(iterations):
        t0 = time.perf_counter()
        await ffbb_bilan_service(organisme_id=9326, categorie="U11M1")
        t1 = time.perf_counter()
        await get_calendrier_club_service(organisme_id=9326, categorie="U11M1")
        t2 = time.perf_counter()
        bilan_times.append(t1 - t0)
        calendrier_times.append(t2 - t1)

    def stats(name, data):
        s = sorted(data)
        p95 = s[int(len(s) * 0.95) - 1] if len(s) >= 1 else 0
        print(
            f"{name}: n={len(s)} mean={mean(s):.6f}s median={median(s):.6f}s p95={p95:.6f}s min={s[0]:.6f}s max={s[-1]:.6f}s"
        )

    stats("ffbb_bilan_service", bilan_times)
    stats("get_calendrier_club_service", calendrier_times)

    # Optionally enforce thresholds (exit non-zero for CI)
    try:
        p95_bilan_thr = float(os.environ.get("THRESHOLD_P95_BILAN", "0"))
        p95_cal_thr = float(os.environ.get("THRESHOLD_P95_CAL", "0"))
    except ValueError:
        p95_bilan_thr = p95_cal_thr = 0.0

    def p95(data):
        s = sorted(data)
        return s[int(len(s) * 0.95) - 1] if len(s) >= 1 else 0

    exit_code = 0
    if p95_bilan_thr > 0 and p95(bilan_times) > p95_bilan_thr:
        print(
            f"ERROR: ffbb_bilan_service p95 {p95(bilan_times):.3f}s > threshold {p95_bilan_thr:.3f}s"
        )
        exit_code = 1
    if p95_cal_thr > 0 and p95(calendrier_times) > p95_cal_thr:
        print(
            f"ERROR: get_calendrier_club_service p95 {p95(calendrier_times):.3f}s > threshold {p95_cal_thr:.3f}s"
        )
        exit_code = 1

    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(measure(100))
