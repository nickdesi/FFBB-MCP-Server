from __future__ import annotations

import asyncio
from typing import Any


async def get_client_async(*args, **kwargs):
    import ffbb_mcp.client

    return await ffbb_mcp.client.get_client_async(*args, **kwargs)


from ffbb_mcp.utils import serialize_model

from .common import (
    _extract_salle_id,
    _format_salle_address,
    _safe_call_with_inflight,
    _with_ffbb_semaphore,
)


async def _enrich_with_salle_details(
    data: dict[str, Any], client: Any
) -> dict[str, Any]:
    salle_id = _extract_salle_id(data)
    if not salle_id or data.get("salle_details"):
        return data

    salle = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            f"Get salle {salle_id}",
            lambda: client.get_salle_async(salle_id),
        )
    )
    salle_data = serialize_model(salle) if salle is not None else {}
    if isinstance(salle_data, dict) and salle_data:
        data["salle_details"] = salle_data
        adresse = _format_salle_address(salle_data)
        if adresse:
            data["adresse_salle"] = adresse
    return data


async def _enrich_matches_with_salle_details(matches: list[dict[str, Any]]) -> None:
    salle_ids = list(
        dict.fromkeys(salle_id for m in matches if (salle_id := _extract_salle_id(m)))
    )
    if not salle_ids:
        return

    client = await get_client_async()
    salle_cache: dict[str, dict[str, Any]] = {}

    async def _fetch_salle(salle_id: str) -> tuple[str, dict[str, Any]]:
        salle = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Get salle {salle_id}",
                lambda: client.get_salle_async(salle_id),
            )
        )
        salle_data = serialize_model(salle) if salle is not None else {}
        return salle_id, salle_data

    results = await asyncio.gather(
        *[_fetch_salle(sid) for sid in salle_ids],
        return_exceptions=True,
    )
    for res in results:
        if isinstance(res, tuple):
            salle_id, salle_data = res
            if isinstance(salle_data, dict) and salle_data:
                salle_cache[salle_id] = salle_data

    for match in matches:
        salle_id = _extract_salle_id(match)
        if not salle_id or salle_id not in salle_cache:
            continue
        match["salle_details"] = salle_cache[salle_id]
        adresse = _format_salle_address(salle_cache[salle_id])
        if adresse:
            match["adresse_salle"] = adresse
