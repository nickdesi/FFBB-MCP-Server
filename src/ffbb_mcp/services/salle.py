from __future__ import annotations

import asyncio
from typing import Any

import httpx


async def get_client_async(*args, **kwargs):
    import ffbb_mcp.client

    return await ffbb_mcp.client.get_client_async(*args, **kwargs)


from ffbb_mcp._state import state
from ffbb_mcp.utils import serialize_model

from .common import (
    _cache_get,
    _cache_set,
    _extract_salle_id,
    _format_salle_address,
    _safe_call_with_inflight,
    _with_ffbb_semaphore,
)


async def _enrich_salle_data_with_meilisearch(
    salle_data: dict[str, Any], client: Any
) -> None:
    if not isinstance(salle_data, dict) or not salle_data:
        return
    if not salle_data.get("ville") and not salle_data.get("commune"):
        libelle = salle_data.get("libelle")
        if libelle:
            try:
                search_res = await client.search_salles_async(libelle)
                if getattr(search_res, "hits", None):
                    for hit in search_res.hits:
                        if getattr(hit, "id", None) == salle_data.get("id"):
                            if getattr(hit, "commune", None):
                                salle_data["ville"] = hit.commune.libelle
                                salle_data["code_postal"] = hit.commune.code_postal
                            break
                    else:
                        hit = search_res.hits[0]
                        if getattr(hit, "commune", None):
                            salle_data["ville"] = hit.commune.libelle
                            salle_data["code_postal"] = hit.commune.code_postal
            except httpx.HTTPError, ValueError, TypeError:
                # Soft-fail: l'enrichissement Meilisearch ne doit jamais casser
                # le flux principal (get salle + formatage).
                pass


async def _enrich_with_salle_details(
    data: dict[str, Any], client: Any
) -> dict[str, Any]:
    salle_id = _extract_salle_id(data)
    if not salle_id or data.get("salle_details"):
        return data

    salle_data = _cache_get(state.cache_salle, salle_id, "salle")
    if salle_data is None:
        salle = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Get salle {salle_id}",
                lambda: client.get_salle_async(salle_id),
            )
        )
        salle_data = serialize_model(salle) if salle is not None else {}
        if isinstance(salle_data, dict) and salle_data:
            await _enrich_salle_data_with_meilisearch(salle_data, client)
            _cache_set(state.cache_salle, salle_id, salle_data, "salle")

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

    salle_cache: dict[str, dict[str, Any]] = {}
    missing_salle_ids: list[str] = []

    for sid in salle_ids:
        cached = _cache_get(state.cache_salle, sid, "salle")
        if cached is not None:
            salle_cache[sid] = cached
        else:
            missing_salle_ids.append(sid)

    if missing_salle_ids:
        client = await get_client_async()

        async def _fetch_salle(salle_id: str) -> tuple[str, dict[str, Any]]:
            salle = await _with_ffbb_semaphore(
                _safe_call_with_inflight(
                    f"Get salle {salle_id}",
                    lambda: client.get_salle_async(salle_id),
                )
            )
            salle_data = serialize_model(salle) if salle is not None else {}
            if isinstance(salle_data, dict) and salle_data:
                await _enrich_salle_data_with_meilisearch(salle_data, client)
            return salle_id, salle_data

        results = await asyncio.gather(
            *[_fetch_salle(sid) for sid in missing_salle_ids],
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, tuple):
                salle_id, salle_data = res
                if isinstance(salle_data, dict) and salle_data:
                    salle_cache[salle_id] = salle_data
                    _cache_set(state.cache_salle, salle_id, salle_data, "salle")

    for match in matches:
        salle_id = _extract_salle_id(match)
        if not salle_id or salle_id not in salle_cache:
            continue
        match["salle_details"] = salle_cache[salle_id]
        adresse = _format_salle_address(salle_cache[salle_id])
        if adresse:
            match["adresse_salle"] = adresse


async def get_salle_service(salle_id: int | str) -> dict[str, Any]:
    """Récupère les détails enrichis d'une salle par son identifiant."""
    sid = str(salle_id)
    cached = _cache_get(state.cache_salle, sid, "salle")
    if cached is not None:
        return cached

    client = await get_client_async()
    salle = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            f"Get salle {sid}",
            lambda: client.get_salle_async(sid),
        )
    )
    salle_data = serialize_model(salle) if salle is not None else {}
    if isinstance(salle_data, dict) and salle_data:
        await _enrich_salle_data_with_meilisearch(salle_data, client)
        adresse = _format_salle_address(salle_data)
        if adresse:
            salle_data["adresse_formatee"] = adresse
        _cache_set(state.cache_salle, sid, salle_data, "salle")
    return salle_data
