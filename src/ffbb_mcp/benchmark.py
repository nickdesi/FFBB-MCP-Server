"""Benchmark de performance — simule des requêtes utilisateur réelles.

Stocke l'historique des runs dans ~/.cache/ffbb-mcp/benchmark_results.json
et expose une tendance exploitable dans le dashboard.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from ffbb_mcp.services import (
    ffbb_bilan_service,
    ffbb_equipes_club_service,
    search_organismes_service,
)

logger = logging.getLogger("ffbb-mcp")

_BENCHMARK_DIR = (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ffbb-mcp"
)
_BENCHMARK_FILE = _BENCHMARK_DIR / "benchmark_results.json"

_MAX_RUNS = 50
_lock = Lock()


def _persist(runs: list[dict[str, Any]]) -> None:
    _BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _BENCHMARK_FILE.write_text(
            json.dumps({"runs": runs}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Erreur écriture benchmark: %s", e)


def _load_history() -> list[dict[str, Any]]:
    try:
        if _BENCHMARK_FILE.exists():
            data = json.loads(_BENCHMARK_FILE.read_text(encoding="utf-8"))
            return data.get("runs", [])
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Erreur lecture benchmark: %s", e)
    return []


async def run_benchmark() -> dict[str, Any]:
    """Exécute un benchmark complet : recherche club → équipes → bilan.

    Retourne le résultat du run avec durée totale et par étape.
    """
    scenario = "bilan U11M1 Stade Clermontois"
    steps: list[dict[str, Any]] = []

    async def _step(name: str, coro) -> Any:
        t0 = time.perf_counter()
        try:
            result = await coro
            steps.append(
                {
                    "name": name,
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                }
            )
            return result
        except Exception as e:
            steps.append(
                {
                    "name": name,
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "error": str(e),
                }
            )
            raise

    try:
        orgs = await _step(
            "search_club", search_organismes_service(nom="Stade Clermontois")
        )
        if not orgs:
            raise ValueError("Club non trouvé")
        org_id = orgs[0].get("id")
        if not org_id:
            raise ValueError("ID club manquant")

        equipes = await _step(
            "get_equipes", ffbb_equipes_club_service(organisme_id=org_id, filtre="U11M")
        )
        if not equipes:
            raise ValueError("Aucune équipe U11M trouvée")

        bilan = await _step(
            "get_bilan", ffbb_bilan_service(organisme_id=org_id, categorie="U11M")
        )
        if not bilan:
            raise ValueError("Bilan vide")

        total_ms = round(sum(s["duration_ms"] for s in steps), 1)
        run = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scenario": scenario,
            "steps": steps,
            "total_ms": total_ms,
            "success": True,
            "error": None,
        }

        with _lock:
            history = _load_history()
            history.append(run)
            if len(history) > _MAX_RUNS:
                history = history[-_MAX_RUNS:]
            _persist(history)

        logger.info("Benchmark OK: %s — %dms", scenario, total_ms)
        return run

    except Exception as e:
        total_ms = round(sum(s["duration_ms"] for s in steps), 1)
        run = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scenario": scenario,
            "steps": steps,
            "total_ms": total_ms,
            "success": False,
            "error": str(e),
        }

        with _lock:
            history = _load_history()
            history.append(run)
            if len(history) > _MAX_RUNS:
                history = history[-_MAX_RUNS:]
            _persist(history)

        logger.warning("Benchmark ECHEC: %s — %s", scenario, e)
        return run


def get_benchmark_trends() -> dict[str, Any]:
    """Retourne les tendances calculées depuis l'historique."""
    with _lock:
        runs = _load_history()

    if not runs:
        return {
            "runs": [],
            "latest": None,
            "average_ms": None,
            "success_rate": 100.0,
            "direction": "unknown",
        }

    successful = [r for r in runs if r["success"]]
    total = len(runs)
    success_rate = round(len(successful) / total * 100, 1) if total else 100.0

    avg_times = [r["total_ms"] for r in successful]
    avg_ms = round(sum(avg_times) / len(avg_times), 1) if avg_times else None

    direction = "unknown"
    if len(successful) >= 3:
        recent = [r["total_ms"] for r in successful[-3:]]
        if recent[2] < recent[0] * 0.9:
            direction = "improving"
        elif recent[2] > recent[0] * 1.1:
            direction = "degrading"
        else:
            direction = "stable"

    return {
        "runs": runs,
        "latest": runs[-1],
        "average_ms": avg_ms,
        "success_rate": success_rate,
        "direction": direction,
        "total_runs": total,
    }


def reset_benchmark() -> None:
    """Réinitialise l'historique des benchmarks (usage tests)."""
    with _lock:
        _persist([])
