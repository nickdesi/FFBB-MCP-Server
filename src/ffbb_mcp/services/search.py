from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache
from typing import Any, Protocol, cast

import httpx
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData
from pydantic import ValidationError

from ffbb_mcp._state import state


async def get_client_async(*args, **kwargs):
    import ffbb_mcp.client

    return await ffbb_mcp.client.get_client_async(*args, **kwargs)


from ffbb_mcp.aliases import (
    _build_fallback_queries,
    enrich_acronym_cache,
    normalize_query,
)
from ffbb_mcp.utils import (
    jaro_winkler_similarity,
    parse_categorie,
    serialize_model,
)

from .common import (
    _ELIMINATION_KEYWORDS,
    _coerce_numeric_id,
    _dedupe_inflight,
    _extract_phase_num,
    _normalize_name,
    _safe_call_with_inflight,
    _with_ffbb_semaphore,
)
from .salle import _enrich_with_salle_details

logger = logging.getLogger("ffbb-mcp")

_NUMERIC_EXTRACT_PATTERN = re.compile(r"(\d+)")


def _phase_sort_key(e: dict) -> tuple[int, int, int]:
    """Clé de tri pour sélectionner la phase la plus avancée.

    Priorité :
    1. Phase éliminatoire > phase de poule
    2. Numéro de phase le plus élevé
    3. Niveau le plus élevé
    """
    competition = e.get("competition") or ""
    is_elimination = 1 if _ELIMINATION_KEYWORDS.search(competition) else 0
    phase_num = _extract_phase_num(e.get("phase_label") or competition)
    niveau = e.get("niveau") or 0
    return (is_elimination, phase_num, niveau)


_PHASE_PATTERN = re.compile(
    r"\s*[-–]\s*(phase\s*\d+|1/\d+\s*finales?|demi[- ]finales?|quarts?|finales?|poules?|brassage|plateaux?)\b.*",  # noqa: RUF001
    re.IGNORECASE,
)


def _extract_base_competition_name(comp_name: str) -> str:
    if not comp_name:
        return ""
    base = _PHASE_PATTERN.sub("", comp_name).strip()
    return _normalize_name(base)


def _is_coupe_competition(comp_name: str, comp_type: str | None) -> bool:
    if comp_type and comp_type.upper() == "COUPE":
        return True
    norm = _normalize_name(comp_name)
    return (
        "COUPE" in norm or "CHALLENGE" in norm or "TROFEE" in norm or "TROPHEE" in norm
    )


def _deduplicate_same_team_phases(candidates: list[dict]) -> list[dict]:
    """Déduplique les candidats qui sont la même équipe au sein de la MÊME compétition (phases successives).

    Ne déduplique JAMAIS si les candidats appartiennent à des compétitions ou types de compétition distincts
    (ex: Championnat vs Coupe ARA).
    """
    if len(candidates) <= 1:
        return candidates

    # Regrouper par (team_name, is_coupe, base_competition_name)
    # Les phases d'un même championnat pour une même équipe partagent (nom_equipe, False)
    groups: dict[tuple[str, bool, str], list[dict]] = {}
    for c in candidates:
        team_name = _normalize_name(c.get("nom_equipe") or c.get("team_label") or "")
        comp_name = c.get("competition") or c.get("competition_code") or ""
        comp_type = c.get("competition_type")
        is_coupe = _is_coupe_competition(comp_name, comp_type)
        base_comp = _extract_base_competition_name(comp_name)

        key = (team_name, is_coupe, base_comp if is_coupe else "")
        groups.setdefault(key, []).append(c)

    deduped: list[dict] = []
    for group in groups.values():
        if len(group) == 1:
            deduped.append(group[0])
        else:
            best = max(group, key=_phase_sort_key)
            deduped.append(best)

    return deduped


# Mots génériques qui n'identifient pas un club de manière distinctive.
_GENERIC_CLUB_WORDS: frozenset[str] = frozenset(
    [
        "BASKET",
        "BASKETBALL",
        "BALL",
        "CLUB",
        "BC",
        "BBC",
        "ABC",
        "BB",
        "CB",
        "SB",
        "JS",
        "AC",
        "AS",
        "US",
        "FC",
        "UNION",
        "ASSOCIATION",
        "SPORTING",
        "SPORT",
        "SPORTS",
        "GARDE",
        "ENTENTE",
        "STADE",
        "ETOILE",
        "AMICALE",
        "OLYMPIQUE",
        "PATRONAGE",
        "JEUNESSE",
        "AVENIR",
        "CERCLE",
        "ES",
        "CS",
        "EB",
        "AL",
        "CA",
        "SA",
        "PL",
    ]
)

# Mapping de configuration pour les types de recherche non exposés individuellement.
_SEARCH_TYPE_METHOD: dict[str, str] = {
    "organismes": "search_organismes_async",
    "competitions": "search_competitions_async",
    "salles": "search_salles_async",
    "rencontres": "search_rencontres_async",
    "pratiques": "search_pratiques_async",
    "terrains": "search_terrains_async",
    "tournois": "search_tournois_async",
    "engagements": "search_engagements_async",
    "formations": "search_formations_async",
    "officiels": "search_officiels_async",
    "entraineurs": "search_entraineurs_async",
    "communes": "search_communes_async",
}


class _CacheSupportsSetItem(Protocol):
    def __setitem__(self, key: Any, value: Any) -> None: ...


class SupportsAssetUrl(Protocol):
    def get_asset_url(
        self,
        *,
        uuid: str,
        width: int | None = None,
        height: int | None = None,
        format: str | None = None,
        quality: int | None = None,
    ) -> str: ...


def _build_club_candidate(
    org: dict[str, Any], nom: str, fallback_id: Any = None
) -> dict[str, Any]:
    """Construit un dict candidat enrichi à partir d'un organisme (hit ou détail)."""
    if not isinstance(org, dict):
        org = {}
    commune = org.get("commune")
    if not isinstance(commune, dict):
        commune = {}
    return {
        "nom": nom,
        "organisme_id": org.get("id") or fallback_id,
        "code": org.get("code", ""),
        "ville": commune.get("libelle"),
        "code_postal": commune.get("code_postal") or commune.get("codePostal"),
        "departement": commune.get("departement"),
        "genre": "F" if "FEMININ" in _normalize_name(nom) else None,
    }


@lru_cache(maxsize=512)
def _extract_club_key_word(club_name: str) -> str | None:
    """Extrait le mot distinctif d'un nom de club en supprimant les termes génériques.

    Exemple : 'Gerzat Basket' → 'GERZAT', 'BC Clermont' → 'CLERMONT'.
    Retourne None si aucun mot distinctif d'au moins 4 caractères n'est trouvé,
    ou si le mot distinctif coïncide avec le nom normalisé complet (aucun apport).
    """
    norm = _normalize_name(club_name)
    words = norm.split()
    for w in words:
        if len(w) >= 4 and w not in _GENERIC_CLUB_WORDS:
            # Inutile de chercher si le mot-clé représente déjà toute la requête normalisée
            if w == norm:
                return None
            return w
    return None


def _filter_orgs_by_gender(
    orgs: list[dict],
    categorie: str,
    club_name: str,
) -> list[dict]:
    """Filtre la liste d'organismes selon le genre (M/F) extrait de la catégorie.

    Règles :
    - Si le nom du club contient déjà "FEMININ", pas de filtrage (choix explicite).
    - Genre 'F' → priorise les organismes dont le nom contient "FEMININ".
    - Genre 'M' → priorise les organismes ne contenant PAS "FEMININ".
    - Si aucun organisme ne matche le genre demandé, la liste originale est retournée.
    """
    if len(orgs) <= 1:
        return orgs

    parsed = parse_categorie(categorie)
    gender = parsed.sexe  # 'M' or 'F' or None

    # Si le nom fourni contient déjà "FEMININ", on ne filtre pas (choix explicite)
    name_norm = _normalize_name(club_name)
    is_explicit_fem = "FEMININ" in name_norm

    if not gender or is_explicit_fem:
        return orgs

    fem_orgs = [o for o in orgs if "FEMININ" in _normalize_name(str(o.get("nom", "")))]
    gen_orgs = [
        o for o in orgs if "FEMININ" not in _normalize_name(str(o.get("nom", "")))
    ]

    if gender == "F" and fem_orgs:
        return fem_orgs
    elif gender == "M" and gen_orgs:
        return gen_orgs

    return orgs


def _build_resolved_entries(orgs: list[dict]) -> list[dict[str, Any]]:
    """Convertit la liste brute d'organismes en entrées résolues standardisées.

    Chaque entrée contient les clés 'nom', 'organisme_id', 'code', 'ville',
    'code_postal', 'departement' et 'genre'.
    Enrichit automatiquement le cache d'acronymes pour chaque nom rencontré.
    """
    resolved: list[dict[str, Any]] = []
    for org in orgs:
        if isinstance(org, dict) and org.get("id"):
            nom = org.get("nom", "")
            resolved.append(_build_club_candidate(org, nom))
            if nom:
                enrich_acronym_cache(nom)
    return resolved


def _resolve_ententes(
    ent_orgs_raw: list[dict],
    existing_ids: set[str],
    key_word: str,
    club_name: str,
) -> list[dict[str, Any]]:
    """Extrait les ententes (ENT.) d'une recherche secondaire et les ajoute aux résultats.

    Une entente est un organisme dont le nom normalisé commence par "ENT." ou "ENT "
    et qui contient le mot-clé distinctif du club recherché.
    Retourne les nouvelles entrées résolues à ajouter.
    """
    additions: list[dict[str, Any]] = []
    key_word_norm = _normalize_name(key_word)

    for ent_org in ent_orgs_raw:
        if not isinstance(ent_org, dict):
            continue
        oid = str(ent_org.get("id", ""))
        if not oid or oid in existing_ids:
            continue
        nom_norm = _normalize_name(str(ent_org.get("nom", "")))
        # Inclure uniquement les ententes (nom commençant par "ENT.")
        # qui contiennent le mot-clé distinctif du club recherché.
        is_entente = nom_norm.startswith("ENT.") or nom_norm.startswith("ENT ")
        if is_entente and key_word_norm in nom_norm:
            nom = ent_org.get("nom", "")
            additions.append(_build_club_candidate(ent_org, nom))
            existing_ids.add(oid)
            logger.debug(
                "ffbb_resolve: entente détectée '%s' (id=%s) pour club_name='%s'",
                nom,
                oid,
                club_name,
            )

    return additions


def _resolve_team_number(
    equipes: list[dict],
    target_num: str | None,
) -> list[dict]:
    """Filtre les équipes par numéro avec fallback sur équipe sans numéro explicite.

    Si target_num est fourni, cherche d'abord les équipes dont numero_equipe
    correspond exactement. En l'absence de match, fallback sur les équipes sans
    numéro (None ou chaîne vide).
    Retourne la liste filtrée (vide si aucun match).
    """
    if not target_num:
        return equipes

    # Filtre exact sur le numéro
    matched = [
        e for e in equipes if (e.get("numero_equipe") or "").strip() == target_num
    ]

    if not matched:
        # Fallback sur équipe sans numéro
        matched = [e for e in equipes if not (e.get("numero_equipe") or "").strip()]

    return matched


async def resolve_club_and_org(
    club_name: str | None,
    organisme_id: int | str | None,
    categorie: str | None = None,
    limit: int = 5,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], dict | None]:
    """Centralise la résolution d'un club vers une liste d'organismes candidats.
    Retourne (candidats, premier_org_data).

    Si categorie est fournie, applique une logique de filtrage M/F.
    """
    import copy

    from ffbb_mcp.services.common import _cache_get, _cache_set

    cache_key = f"resolve_club:{club_name}:{organisme_id}:{categorie}:{limit}"
    if not force_refresh:
        cached = _cache_get(state.cache_resolve_club, cache_key, "resolve_club")
        if cached is not None:
            return copy.deepcopy(cached)

    import ffbb_mcp.services

    resolved: list[dict[str, Any]] = []
    org_data = None

    if organisme_id is not None:
        try:
            org_info = await ffbb_mcp.services.get_organisme_service(str(organisme_id))
            if org_info and isinstance(org_info, dict):
                org_data = org_info
                resolved.append(
                    _build_club_candidate(
                        org_info,
                        org_info.get("nom", "") or str(organisme_id),
                        fallback_id=organisme_id,
                    )
                )
            else:
                logger.warning("Organisme retourné vide ou invalide")
        except httpx.HTTPError, McpError, ValidationError:
            logger.debug(
                "Impossible de charger l'organisme",
                exc_info=True,
            )
    elif club_name:
        # Recherche secondaire parallèle pour les ententes (ENT. CLUB_A / CLUB_B).
        # Une entente est un organisme distinct dont le nom commence par "ENT." et
        # contient le mot distinctif du club (ex: "Gerzat Basket" → "GERZAT").
        key_word = _extract_club_key_word(club_name)
        search_tasks: list[Any] = [
            ffbb_mcp.services.search_organismes_service(nom=club_name, limit=limit)
        ]
        if key_word:
            search_tasks.append(
                ffbb_mcp.services.search_organismes_service(
                    nom=key_word, limit=limit + 5
                )
            )
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        orgs: list[dict] = (
            search_results[0] if isinstance(search_results[0], list) else []
        )
        ent_orgs_raw: list[dict] = (
            search_results[1]
            if len(search_tasks) > 1 and isinstance(search_results[1], list)
            else []
        )

        # Application du Smart Resolution M/F
        if categorie:
            orgs = _filter_orgs_by_gender(orgs, categorie, club_name)

        if orgs:
            # On récupère le détail du premier pour avoir les métadonnées riches
            try:
                first_org_id = orgs[0].get("id")
                if first_org_id:
                    org_data = await ffbb_mcp.services.get_organisme_service(
                        first_org_id
                    )
            except httpx.HTTPError, McpError, ValidationError:
                logger.debug(
                    "Impossible de charger les détails du premier organisme pour %s",
                    club_name,
                    exc_info=True,
                )

        resolved = _build_resolved_entries(orgs)

        # Ajout des ententes associées issues de la recherche secondaire.
        norm_club_name = _normalize_name(club_name)
        if key_word and ent_orgs_raw:
            existing_ids = {str(r["organisme_id"]) for r in resolved}
            ententes = _resolve_ententes(
                ent_orgs_raw, existing_ids, key_word, club_name
            )
            if categorie:
                ententes = _filter_orgs_by_gender(ententes, categorie, club_name)
            resolved.extend(ententes)

        # Jaro-Winkler Sorting Optimization avec priorité absolue au match exact
        if len(resolved) > 1 and club_name:
            resolved.sort(
                key=lambda c: (
                    2.0
                    if _normalize_name(c.get("nom", "")) == norm_club_name
                    else jaro_winkler_similarity(club_name, c["nom"])
                ),
                reverse=True,
            )

    result = (resolved, org_data)
    _cache_set(
        state.cache_resolve_club,
        cache_key,
        copy.deepcopy(result),
        "resolve_club",
    )
    return result


from ffbb_data_client.config import (
    MEILISEARCH_INDEX_COMPETITIONS,
    MEILISEARCH_INDEX_ENGAGEMENTS,
    MEILISEARCH_INDEX_FORMATIONS,
    MEILISEARCH_INDEX_GALERIES,
    MEILISEARCH_INDEX_NEWS,
    MEILISEARCH_INDEX_ORGANISMES,
    MEILISEARCH_INDEX_PRATIQUES,
    MEILISEARCH_INDEX_RENCONTRES,
    MEILISEARCH_INDEX_RSS,
    MEILISEARCH_INDEX_SALLES,
    MEILISEARCH_INDEX_TERRAINS,
    MEILISEARCH_INDEX_TOURNOIS,
)

_SEARCH_INDEX_MAP: dict[str, str] = {
    "organismes": MEILISEARCH_INDEX_ORGANISMES,
    "competitions": MEILISEARCH_INDEX_COMPETITIONS,
    "rencontres": MEILISEARCH_INDEX_RENCONTRES,
    "salles": MEILISEARCH_INDEX_SALLES,
    "pratiques": MEILISEARCH_INDEX_PRATIQUES,
    "terrains": MEILISEARCH_INDEX_TERRAINS,
    "tournois": MEILISEARCH_INDEX_TOURNOIS,
    "engagements": MEILISEARCH_INDEX_ENGAGEMENTS,
    "formations": MEILISEARCH_INDEX_FORMATIONS,
    "news": MEILISEARCH_INDEX_NEWS,
    "galeries": MEILISEARCH_INDEX_GALERIES,
    "rss": MEILISEARCH_INDEX_RSS,
}

_PRIMARY_SEARCH_INDEXES = {
    MEILISEARCH_INDEX_ORGANISMES,
    MEILISEARCH_INDEX_COMPETITIONS,
    MEILISEARCH_INDEX_RENCONTRES,
}

_ALL_CANDIDATE_SEARCH_INDEXES = [
    MEILISEARCH_INDEX_ORGANISMES,
    MEILISEARCH_INDEX_COMPETITIONS,
    MEILISEARCH_INDEX_RENCONTRES,
    MEILISEARCH_INDEX_SALLES,
    MEILISEARCH_INDEX_TERRAINS,
    MEILISEARCH_INDEX_TOURNOIS,
]


def _build_search_results(results: Any, limit: int, offset: int = 0) -> list[dict]:
    """Construit la liste de résultats et attache _total_hits si pagination/troncature."""
    if not results or not getattr(results, "hits", None):
        return []
    result_list = [serialize_model(hit) for hit in results.hits[:limit]]
    total = getattr(results, "estimated_total_hits", None)
    if total is not None:
        for item in result_list:
            item["_total_hits"] = total
            item["_offset"] = offset
    return result_list


async def _search_generic(
    type_name: str,
    query: str,
    limit: int = 20,
    offset: int = 0,
    filter_by: str | None = None,
    sort: list[str] | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    from ffbb_data_client.models import MultiSearchQuery

    normalized_query = normalize_query(query)
    filter_part = filter_by or ""
    sort_part = ",".join(sort) if sort else ""
    cache_key = f"search:{type_name}:{normalized_query}:{limit}:{offset}:{filter_part}:{sort_part}"

    async def _fetch() -> list[dict[str, Any]]:
        client = await get_client_async()

        # Si une méthode de recherche directe existe sur le client (ex: search_organismes_async)
        method_name = _SEARCH_TYPE_METHOD.get(type_name)
        direct_method: Any = getattr(client, method_name, None) if method_name else None
        if direct_method and callable(direct_method):
            try:

                async def _invoke_direct() -> Any:
                    import inspect

                    try:
                        res: Any = direct_method(query, limit=limit)
                    except TypeError:
                        res = direct_method(nom=query, limit=limit)
                    if inspect.isawaitable(res):
                        return await res  # type: ignore[no-any-return]
                    return res

                direct_res = await _with_ffbb_semaphore(
                    _safe_call_with_inflight(
                        f"Search direct {type_name}: {query}",
                        _invoke_direct,
                    )
                )
                if direct_res is not None and getattr(direct_res, "hits", None):
                    return _build_search_results(direct_res, limit, offset)
            except Exception:
                pass

        index_uid = _SEARCH_INDEX_MAP.get(type_name, type_name)
        filter_list = [filter_by] if filter_by else None
        q = [
            MultiSearchQuery(
                index_uid=index_uid,
                q=normalized_query,
                limit=limit,
                offset=offset,
                filter=filter_list,
                sort=sort,
            )
        ]

        def _call_ms(queries: Any) -> Any:
            meili = getattr(client, "_meilisearch", None)
            if (
                meili
                and hasattr(meili, "multi_search_async")
                and callable(meili.multi_search_async)
            ):
                return meili.multi_search_async(queries)
            if hasattr(client, "multi_search_async") and callable(
                client.multi_search_async
            ):
                return client.multi_search_async(queries)
            return client._meilisearch.multi_search_async(queries)

        results = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Search {type_name}: {query}",
                lambda: _call_ms(q),
            )
        )
        if (
            not results
            or not getattr(results, "results", None)
            or not results.results[0].hits
        ):
            # Fallback : essayer les variantes de requête
            fallbacks = _build_fallback_queries(query)
            for fb in fallbacks:
                if fb == query:
                    continue
                q_fb = [
                    MultiSearchQuery(
                        index_uid=index_uid,
                        q=normalize_query(fb),
                        limit=limit,
                        offset=offset,
                        filter=filter_list,
                        sort=sort,
                    )
                ]
                results = await _with_ffbb_semaphore(
                    _safe_call_with_inflight(
                        f"Search {type_name} (fallback): {fb}",
                        lambda q_target=q_fb: _call_ms(q_target),
                    )
                )
                if (
                    results
                    and getattr(results, "results", None)
                    and results.results[0].hits
                ):
                    break

        if not results or not getattr(results, "results", None):
            return []

        res0 = results.results[0]
        hits = [serialize_model(h) for h in res0.hits]
        total = getattr(res0, "estimated_total_hits", len(hits))
        if total is not None:
            for item in hits:
                item["_total_hits"] = total
                item["_offset"] = offset
        return hits

    return await _dedupe_inflight(
        cache=state.cache_search,
        cache_key=cache_key,
        inflight_map=state.inflight_search,
        make_coro=_fetch,
        cache_name="search",
        force_refresh=force_refresh,
    )


async def search_organismes_service(
    nom: str,
    limit: int = 20,
    offset: int = 0,
    filter_by: str | None = None,
    sort: list[str] | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    return await _search_generic(
        "organismes",
        nom,
        limit=limit,
        offset=offset,
        filter_by=filter_by,
        sort=sort,
        force_refresh=force_refresh,
    )


def _build_multi_search_queries(
    active_indexes: list[str],
    normalized_query: str,
    limit: int,
) -> list[Any]:
    from ffbb_data_client.models import MultiSearchQuery

    primary_limit = min(limit, max(2, (limit + 2) // 3))
    secondary_limit = min(limit, max(1, (limit + 9) // 10))

    return [
        MultiSearchQuery(
            index_uid=idx,
            q=normalized_query,
            limit=primary_limit if idx in _PRIMARY_SEARCH_INDEXES else secondary_limit,
        )
        for idx in active_indexes
    ]


async def _execute_multi_search_with_self_healing(
    client: Any,
    nom: str,
    normalized_query: str,
    limit: int,
) -> Any:
    """Exécute un multi-search Meilisearch avec auto-découverte et boucle de self-healing."""
    from ffbb_data_client.models import MultiSearchQuery

    if state.active_search_indexes is None:
        # Résolution dynamique initiale via discovery
        try:
            from ffbb_data_client.data import load_discovery_artefact

            disc = load_discovery_artefact("indexes.json")
            available = set(disc.get("available_indexes", []))
            if available:
                state.active_search_indexes = [
                    idx for idx in _ALL_CANDIDATE_SEARCH_INDEXES if idx in available
                ]
        except Exception:
            pass

        if not state.active_search_indexes:
            state.active_search_indexes = list(_ALL_CANDIDATE_SEARCH_INDEXES)

    active_indexes = list(state.active_search_indexes)
    queries = _build_multi_search_queries(active_indexes, normalized_query, limit)

    def _call_ms(q_list: Any) -> Any:
        if hasattr(client, "multi_search_async") and callable(
            client.multi_search_async
        ):
            return client.multi_search_async(q_list)
        return client._meilisearch.multi_search_async(q_list)

    try:
        return await _with_ffbb_semaphore(
            _safe_call_with_inflight(f"Multi-search: {nom}", lambda: _call_ms(queries))
        )
    except Exception as e:
        logger.warning(
            "Échec multi-search initial (%s) — Déclenchement de l'auto-guérison (Self-Healing)...",
            e,
        )
        # Diagnostic / Sonde rapide pour identifier les index opérationnels
        healthy_indexes: list[str] = []
        for idx in active_indexes:
            try:
                single_q = [
                    MultiSearchQuery(index_uid=idx, q=normalized_query, limit=1)
                ]
                probe = await client._meilisearch.multi_search_async(single_q)
                if (
                    probe
                    and getattr(probe, "results", None)
                    and len(probe.results) == 1
                ):
                    healthy_indexes.append(idx)
                else:
                    logger.info("Self-Healing : index inactif ou vide exclu : %s", idx)
            except Exception:
                logger.info("Self-Healing : index en erreur exclu : %s", idx)

        if not healthy_indexes:
            healthy_indexes = [
                MEILISEARCH_INDEX_ORGANISMES,
                MEILISEARCH_INDEX_COMPETITIONS,
            ]

        # Cristallisation des index sains en mémoire
        state.active_search_indexes = healthy_indexes
        recovered_queries = _build_multi_search_queries(
            healthy_indexes, normalized_query, limit
        )
        return await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Multi-search (auto-healed): {nom}",
                lambda: _call_ms(recovered_queries),
            )
        )


async def multi_search_service(
    nom: str,
    limit: int = 20,
    offset: int = 0,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    normalized_query = normalize_query(nom)
    cache_key = f"multi_search:{normalized_query}:{limit}:{offset}"

    async def _fetch() -> list[dict[str, Any]]:
        client = await get_client_async()
        # Pour supporter l'offset, on fetch offset+limit puis on slice côté MCP
        fetch_limit = offset + limit if offset else limit
        raw = await _execute_multi_search_with_self_healing(
            client=client,
            nom=nom,
            normalized_query=normalized_query,
            limit=fetch_limit,
        )

        if not getattr(raw, "results", None):
            return []

        output: list[dict[str, Any]] = []
        total_hits: int | None = None
        for res in raw.results:
            category = res.index_uid
            est = getattr(res, "estimated_total_hits", None)
            # Ne comptabiliser que les vrais entiers (évite MagicMock en test)
            if isinstance(est, int):
                total_hits = (total_hits or 0) + est
            elif isinstance(est, float):
                total_hits = int((total_hits or 0) + est)
            for hit in res.hits:
                item = serialize_model(hit)
                item["_type"] = category
                output.append(item)
                if len(output) >= fetch_limit:
                    break
            if len(output) >= fetch_limit:
                break
        # Slice pour pagination offset
        sliced = output[offset : offset + limit] if offset else output[:limit]
        if total_hits is not None and total_hits > len(sliced):
            for out_item in sliced:
                out_item["_total_hits"] = total_hits
                out_item["_offset"] = offset
        elif offset:
            for out_item in sliced:
                out_item["_offset"] = offset
                if total_hits is not None and total_hits:
                    out_item["_total_hits"] = total_hits
        return sliced

    return await _dedupe_inflight(
        cache=state.cache_search,
        cache_key=cache_key,
        inflight_map=state.inflight_search,
        make_coro=_fetch,
        cache_name="search",
        force_refresh=force_refresh,
    )


def _add_truncation_meta(
    result: list[dict[str, Any]],
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Enveloppe le résultat de recherche avec des métadonnées de pagination.

    Retourne un dict ``{"items": [...], "_meta": {...}}`` au lieu d'une liste brute.
    """
    if not result:
        return {
            "items": [],
            "_meta": {
                "total": 0,
                "returned": 0,
                "limit": limit,
                "offset": offset,
                "has_more": False,
            },
        }

    total = result[0].pop("_total_hits", None)
    result_offset = result[0].pop("_offset", offset)
    for item in result[1:]:
        item.pop("_total_hits", None)
        item.pop("_offset", None)

    effective_total = total if total is not None else len(result)
    has_more = (result_offset + len(result)) < effective_total
    next_offset = (result_offset + len(result)) if has_more else None

    meta: dict[str, Any] = {
        "total": effective_total,
        "returned": len(result),
        "limit": limit,
        "offset": result_offset,
        "has_more": has_more,
    }
    if next_offset is not None:
        meta["next_offset"] = next_offset
    if has_more:
        meta["truncated"] = True

    return {
        "items": result,
        "_meta": meta,
    }


async def ffbb_search_service(
    *,
    type: str = "all",
    query: str,
    limit: int = 20,
    offset: int = 0,
    filter_by: str | None = None,
    sort: list[str] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Service de recherche FFBB unifié avec support complet de limit et offset.

    Recherche dans les données FFBB (organismes, compétitions, rencontres, salles, tournois...).
    """
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    if type == "all":
        result = await multi_search_service(
            nom=query, limit=limit, offset=offset, force_refresh=force_refresh
        )
        if not isinstance(result, list):
            return []
        # multi_search_service déjà slice, mais on garde offset meta cohérente
        return _add_truncation_meta(result, limit=limit, offset=offset)

    if type == "organismes":
        result = await search_organismes_service(
            query,
            limit=limit,
            offset=offset,
            filter_by=filter_by,
            sort=sort,
            force_refresh=force_refresh,
        )
        return _add_truncation_meta(result, limit=limit, offset=offset)

    if type in _SEARCH_INDEX_MAP:
        result = await _search_generic(
            type_name=type,
            query=query,
            limit=limit,
            offset=offset,
            filter_by=filter_by,
            sort=sort,
            force_refresh=force_refresh,
        )
        return _add_truncation_meta(result, limit=limit, offset=offset)

    raise McpError(
        error=ErrorData(
            code=INTERNAL_ERROR,
            message=f"Type de recherche inconnu: {type}. Types supportés: {', '.join(['all', *list(_SEARCH_INDEX_MAP.keys())])}",
        )
    )


async def ffbb_resolve_team_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    numero_equipe: int | str | None = None,
    engagement_id: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    poule_id: int | str | None = None,
    season_id: int | str | None = None,
    force_refresh: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Résout une équipe unique d'un club pour une catégorie donnée.

    Retourne un objet structuré et déterministe pour les agents :
      - `status`: "resolved" | "ambiguous" | "not_found"
      - `team`: engagement résolu (ou None si ambigu / introuvable)
      - `candidates`: liste des engagements candidats
      - `ambiguity`: message explicite en cas d'ambiguïté
      - `clarification_prompt`: question exploitable par le LLM pour clarifier
    """
    import ffbb_mcp.services

    if not club_name and not organisme_id:
        raise McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message="Fournir club_name ou organisme_id",
            )
        )

    # 1) Résoudre l'organisme avec métadonnées
    resolved_clubs, _ = await resolve_club_and_org(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        force_refresh=force_refresh,
    )

    if not resolved_clubs:
        return {
            "status": "not_found",
            "team": None,
            "candidates": [],
            "ambiguity": f"Club '{club_name or organisme_id}' introuvable",
            "clarification_prompt": None,
            "club_resolu": None,
        }

    # Si ambiguïté club
    if len(resolved_clubs) > 1 and not organisme_id:
        if categorie:
            matching_clubs: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
            for rc in resolved_clubs:
                rc_id = rc.get("organisme_id")
                if not rc_id:
                    continue
                rc_teams = await ffbb_mcp.services.ffbb_equipes_club_service(
                    organisme_id=rc_id, filtre=categorie, force_refresh=force_refresh
                )
                if rc_teams and not (
                    isinstance(rc_teams, list)
                    and len(rc_teams) == 1
                    and "error" in rc_teams[0]
                ):
                    matching_clubs.append((rc, rc_teams))
            if len(matching_clubs) == 1:
                club_resolu = matching_clubs[0][0]
                equipes = matching_clubs[0][1]
                target_org_id = str(club_resolu["organisme_id"])
            else:
                return {
                    "status": "ambiguous",
                    "team": None,
                    "candidates": resolved_clubs,
                    "ambiguity": f"Plusieurs clubs correspondent à '{club_name}'.",
                    "clarification_prompt": f"Plusieurs clubs correspondent à '{club_name}'. Précisez organisme_id.",
                    "club_resolu": None,
                }
        else:
            return {
                "status": "ambiguous",
                "team": None,
                "candidates": resolved_clubs,
                "ambiguity": f"Plusieurs clubs correspondent à '{club_name}'.",
                "clarification_prompt": f"Plusieurs clubs correspondent à '{club_name}'. Précisez organisme_id.",
                "club_resolu": None,
            }
    else:
        club_resolu = resolved_clubs[0]
        target_org_id = str(club_resolu["organisme_id"])
        equipes = None

    # 2) Récupérer toutes les équipes candidates
    if not categorie:
        equipes = await ffbb_mcp.services.ffbb_equipes_club_service(
            organisme_id=target_org_id, force_refresh=force_refresh
        )
        if not equipes or (
            isinstance(equipes, list) and len(equipes) == 1 and "error" in equipes[0]
        ):
            return {
                "status": "not_found",
                "team": None,
                "candidates": [],
                "ambiguity": f"Aucune équipe trouvée pour le club '{club_resolu.get('nom', target_org_id)}'.",
                "clarification_prompt": None,
                "club_resolu": club_resolu,
            }
        equipes = _deduplicate_same_team_phases(equipes)
        if len(equipes) == 1:
            return {
                "status": "resolved",
                "team": equipes[0],
                "candidates": equipes,
                "ambiguity": None,
                "clarification_prompt": None,
                "club_resolu": club_resolu,
            }
        return {
            "status": "ambiguous",
            "team": None,
            "candidates": equipes,
            "ambiguity": "Veuillez préciser la catégorie souhaitée parmi les équipes du club.",
            "clarification_prompt": "Veuillez préciser la catégorie souhaitée parmi les équipes du club.",
            "club_resolu": club_resolu,
        }

    if equipes is None:
        equipes = await ffbb_mcp.services.ffbb_equipes_club_service(
            organisme_id=target_org_id, filtre=categorie, force_refresh=force_refresh
        )

    if not equipes or (
        isinstance(equipes, list) and len(equipes) == 1 and "error" in equipes[0]
    ):
        msg = (
            equipes[0]["error"]
            if (equipes and "error" in equipes[0])
            else f"Aucune équipe trouvée pour la catégorie '{categorie}'."
        )
        suggestions = (
            equipes[0].get("suggested_teams")
            if (equipes and "suggested_teams" in equipes[0])
            else []
        )
        return {
            "status": "not_found",
            "team": None,
            "candidates": suggestions,
            "ambiguity": msg,
            "clarification_prompt": None,
            "club_resolu": club_resolu,
        }

    # 3) Matching intelligent du numéro
    from .club import _parse_division_code

    candidates = list(equipes)
    parsed = parse_categorie(categorie)
    is_division = _parse_division_code(categorie) is not None
    raw_num = (
        numero_equipe
        if numero_equipe is not None
        else (
            kwargs.get("numero_equipe")
            if kwargs.get("numero_equipe") is not None
            else (parsed.numero_equipe if not is_division else None)
        )
    )
    target_num = str(raw_num) if raw_num is not None else None

    # On cherche d'abord le numéro exact, fallback sur équipe sans numéro
    matched = _resolve_team_number(candidates, target_num)
    if matched:
        candidates = matched

    # 3.5) Application des filtres explicites de désambiguïsation
    if engagement_id is not None:
        target_eng_id = str(engagement_id).strip()
        candidates = [
            c
            for c in candidates
            if str(c.get("engagement_id") or c.get("team_id") or "").strip()
            == target_eng_id
        ]

    if competition_id is not None:
        target_comp_id = str(competition_id).strip()
        candidates = [
            c
            for c in candidates
            if str(c.get("competition_id") or "").strip() == target_comp_id
        ]

    if competition_type is not None:
        target_comp_type = str(competition_type).strip().upper()
        candidates = [
            c
            for c in candidates
            if str(c.get("competition_type") or "").strip().upper() == target_comp_type
        ]

    if poule_id is not None:
        target_poule_id = str(poule_id).strip()
        candidates = [
            c
            for c in candidates
            if str(c.get("poule_id") or "").strip() == target_poule_id
        ]

    # Déduplication sémantique : uniquement au sein d'une MÊME compétition
    candidates = _deduplicate_same_team_phases(candidates)

    # 4) Machine à états de la réponse
    if not candidates:
        all_labels = sorted(list({t["team_label"] for t in equipes}))
        return {
            "status": "not_found",
            "team": None,
            "candidates": all_labels,
            "ambiguity": f"Aucun engagement ne correspond aux critères spécifiés pour '{categorie}'.",
            "clarification_prompt": None,
            "club_resolu": club_resolu,
        }

    if len(candidates) == 1:
        return {
            "status": "resolved",
            "team": candidates[0],
            "candidates": candidates,
            "ambiguity": None,
            "clarification_prompt": None,
            "club_resolu": club_resolu,
        }

    # Plusieurs engagements subsistent → ambiguïté réelle déclarée explicitement
    comp_descriptions = []
    for c in candidates:
        c_label = c.get("competition") or c.get("competition_code") or "Compétition"
        c_type = c.get("competition_type") or "Type inconnu"
        c_id = c.get("competition_id") or ""
        comp_descriptions.append(
            f"'{c_label}' (type: {c_type}, competition_id: {c_id})"
        )

    clarification = (
        f"L'équipe {club_resolu.get('nom', '')} {categorie or ''} participe à {len(candidates)} compétitions distinctes : "
        + " ; ".join(comp_descriptions)
        + ". Précisez `competition_id` ou `competition_type` pour cibler la compétition voulue."
    )

    return {
        "status": "ambiguous",
        "team": None,
        "candidates": candidates,
        "ambiguity": f"Plusieurs engagements ({len(candidates)}) correspondent à cette équipe.",
        "clarification_prompt": clarification,
        "club_resolu": club_resolu,
    }


async def get_rencontre_service(rencontre_id: int | str) -> dict[str, Any]:
    client = await get_client_async()
    result = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            f"Get rencontre {rencontre_id}",
            lambda: client.get_rencontre_async(str(rencontre_id)),
        )
    )
    data = serialize_model(result) if result is not None else {}
    return (
        await _enrich_with_salle_details(data, client) if isinstance(data, dict) else {}
    )


async def get_officiel_service(officiel_id: int | str) -> dict[str, Any]:
    client = await get_client_async()
    result = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            f"Get officiel {officiel_id}",
            lambda: client.get_officiel_async(str(officiel_id)),
        )
    )
    return serialize_model(result) if result is not None else {}


async def get_entraineur_service(entraineur_id: int | str) -> dict[str, Any]:
    client = await get_client_async()
    result = await _with_ffbb_semaphore(
        _safe_call_with_inflight(
            f"Get entraineur {entraineur_id}",
            lambda: client.get_entraineur_async(str(entraineur_id)),
        )
    )
    return serialize_model(result) if result is not None else {}


async def get_asset_url_service(
    uuid: str,
    width: int | None = None,
    height: int | None = None,
    format: str | None = None,
    quality: int | None = None,
) -> str:
    """Construit une URL d'asset Directus optimisée via le client V3."""
    client = cast("SupportsAssetUrl", await get_client_async())
    return client.get_asset_url(
        uuid=uuid,
        width=width,
        height=height,
        format=format,
        quality=quality,
    )


async def resolve_poule_id_service(
    organisme_id: int | str,
    categorie: str,
    phase_query: str | None = None,
) -> str | None:
    """Résout le poule_id d'une équipe pour une phase donnée (ex: 'phase 3').

    Si phase_query est None, retourne le poule_id de l'engagement le plus récent
    (plus haut niveau ou phase chronologique la plus avancée).
    """
    import ffbb_mcp.services

    org_id_int = _coerce_numeric_id(organisme_id, "organisme_id")
    equipes = await ffbb_mcp.services.ffbb_equipes_club_service(
        organisme_id=org_id_int, filtre=categorie
    )
    if not equipes or (
        isinstance(equipes, list) and len(equipes) == 1 and "error" in equipes[0]
    ):
        return None

    if phase_query:
        target_phase = phase_query.strip()
        phase_num_match = _NUMERIC_EXTRACT_PATTERN.search(target_phase)
        target_phase_int: int | None = (
            int(phase_num_match.group(1)) if phase_num_match else None
        )

        for e in equipes:
            if target_phase_int is not None:
                phase_in_label = _extract_phase_num(e.get("phase_label"))
                phase_in_comp = _extract_phase_num(e.get("competition"))
                if (
                    phase_in_label == target_phase_int
                    or phase_in_comp == target_phase_int
                ):
                    return str(e.get("poule_id"))
            else:
                phase_label = (e.get("phase_label") or "").lower()
                if target_phase.lower() in phase_label:
                    return str(e.get("poule_id"))

        return None

    def sort_key(e: dict) -> tuple[int, int]:
        phase_num = _extract_phase_num(e.get("phase_label") or e.get("competition"))
        return (phase_num, e.get("niveau") or 0)

    equipes.sort(key=sort_key, reverse=True)
    return str(equipes[0].get("poule_id"))
