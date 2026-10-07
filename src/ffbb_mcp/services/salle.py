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
    libelle = salle_data.get("libelle") or salle_data.get("nom")
    salle_id = str(salle_data.get("id") or "")
    if libelle:
        try:
            search_res = await client.search_salles_async(libelle)
            hits = getattr(search_res, "hits", None) or []
            matched_hit = None
            for hit in hits:
                if str(getattr(hit, "id", None) or "") == salle_id:
                    matched_hit = hit
                    break
            if matched_hit is None and hits:
                matched_hit = hits[0]

            if matched_hit:
                # 1. Commune / Ville / Code postal
                commune_obj = getattr(matched_hit, "commune", None)
                if commune_obj:
                    if not salle_data.get("ville"):
                        salle_data["ville"] = getattr(commune_obj, "libelle", None)
                    if not salle_data.get("code_postal"):
                        salle_data["code_postal"] = getattr(
                            commune_obj, "code_postal", None
                        )
                    if not salle_data.get("departement"):
                        salle_data["departement"] = getattr(
                            commune_obj, "departement", None
                        )
                # 2. Nom secondaire (libelle2)
                lib2 = getattr(matched_hit, "libelle2", None)
                if lib2 and not salle_data.get("libelle2"):
                    salle_data["libelle2"] = lib2
                # 3. Téléphone
                tel = getattr(matched_hit, "telephone", None)
                if tel and not salle_data.get("telephone"):
                    salle_data["telephone"] = tel
                # 4. Coordonnées GPS / geo
                geo = getattr(matched_hit, "geo", None)
                if geo and not salle_data.get("geo"):
                    salle_data["geo"] = serialize_model(geo)
                # 5. Cartographie
                carto = getattr(matched_hit, "cartographie", None)
                if carto and not salle_data.get("cartographie"):
                    salle_data["cartographie"] = serialize_model(carto)
        except (httpx.HTTPError, ValueError, TypeError):
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
