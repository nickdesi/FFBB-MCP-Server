from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache
from typing import Any, Protocol, cast

import httpx
from mcp.shared.exceptions import ErrorData, McpError
from mcp.types import INTERNAL_ERROR
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


def _deduplicate_same_team_phases(candidates: list[dict]) -> list[dict]:
    """Déduplique les candidats qui sont la même équipe à travers différentes phases.

    Si tous les candidats partagent le même nom_equipe (normalisé),
    ils représentent la même équipe dans des phases successives.
    On retourne uniquement l'entrée de la phase la plus avancée.
    """
    if len(candidates) <= 1:
        return candidates

    # Vérifier si tous les candidats ont le même nom_equipe
    noms = [
        _normalize_name(c.get("nom_equipe") or c.get("team_label") or "")
        for c in candidates
    ]
    unique_noms = {n for n in noms if n}

    if len(unique_noms) <= 1:
        # Même équipe → retourner uniquement la phase la plus avancée
        best = max(candidates, key=_phase_sort_key)
        return [best]

    return candidates


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
    ]
)

# Mapping de configuration pour les types de recherche non exposés individuellement.
_SEARCH_TYPE_METHOD: dict[str, str] = {
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
    key_words = [w for w in words if w not in _GENERIC_CLUB_WORDS and len(w) >= 4]
    if not key_words:
        return None
    candidate = key_words[0]
    # Inutile de chercher si le mot-clé représente déjà toute la requête normalisée
    if candidate == norm:
        return None
    return candidate


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
) -> tuple[list[dict[str, Any]], dict | None]:
    """Centralise la résolution d'un club vers une liste d'organismes candidats.
    Retourne (candidats, premier_org_data).

    Si categorie est fournie, applique une logique de filtrage M/F.
    """
    import copy

    from ffbb_mcp.services.common import _cache_get, _cache_set

    cache_key = f"resolve_club:{club_name}:{organisme_id}:{categorie}:{limit}"
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
        except (httpx.HTTPError, McpError, ValidationError):
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
            except (httpx.HTTPError, McpError, ValidationError):
                logger.debug(
                    "Impossible de charger les détails du premier organisme pour %s",
                    club_name,
                    exc_info=True,
                )

        resolved = _build_resolved_entries(orgs)

        # Ajout des ententes associées issues de la recherche secondaire.
        if key_word and ent_orgs_raw:
            existing_ids = {str(r["organisme_id"]) for r in resolved}
            ententes = _resolve_ententes(
                ent_orgs_raw, existing_ids, key_word, club_name
            )
            resolved.extend(ententes)

        # Jaro-Winkler Sorting Optimization
        if len(resolved) > 1 and club_name:
            resolved.sort(
                key=lambda c: jaro_winkler_similarity(club_name, c["nom"]),
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


def _build_search_results(results: Any, limit: int) -> list[dict]:
    """Construit la liste de résultats et attache _total_hits si troncature."""
    if not results or not results.hits:
        return []
    result_list = [serialize_model(hit) for hit in results.hits[:limit]]
    total = getattr(results, "estimated_total_hits", None)
    if total is not None and total > len(result_list):
        for item in result_list:
            item["_total_hits"] = total
    return result_list


async def _search_generic(
    operation: str,
    method_name: str,
    query: str,
    limit: int = 20,
    filter_by: str | None = None,
    sort: list[str] | None = None,
) -> list[dict]:
    normalized_query = normalize_query(query)
    filter_part = filter_by or ""
    sort_part = ",".join(sort) if sort else ""
    cache_key = (
        f"search:{operation}:{normalized_query}:{limit}:{filter_part}:{sort_part}"
    )

    async def _fetch() -> list[dict]:
        client = await get_client_async()
        method = getattr(client, method_name)
        call_kwargs: dict[str, Any] = {}
        if filter_by:
            call_kwargs["filter_by"] = filter_by
        if sort:
            call_kwargs["sort"] = sort
        results = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Search {operation}: {query}",
                lambda: method(normalized_query, **call_kwargs),
            )
        )
        if not results or not results.hits:
            # Fallback : essayer les variantes de requête
            fallbacks = _build_fallback_queries(query)
            for fb in fallbacks:
                if fb == query:
                    continue
                results = await _with_ffbb_semaphore(
                    _safe_call_with_inflight(
                        f"Search {operation} (fallback): {fb}",
                        lambda fb=fb: method(fb, **call_kwargs),
                    )
                )
                if results and results.hits:
                    return _build_search_results(results, limit)
            return []
        return _build_search_results(results, limit)

    return await _dedupe_inflight(
        cache=state.cache_search,
        cache_key=cache_key,
        inflight_map=state.inflight_search,
        make_coro=_fetch,
        cache_name="search",
    )


async def search_organismes_service(
    nom: str,
    limit: int = 20,
    filter_by: str | None = None,
    sort: list[str] | None = None,
) -> list[dict]:
    return await _search_generic(
        "organismes", "search_organismes_async", nom, limit, filter_by, sort
    )


async def multi_search_service(nom: str, limit: int = 20) -> list[dict[str, Any]]:
    normalized_query = normalize_query(nom)
    cache_key = f"multi_search:{normalized_query}:{limit}"

    async def _fetch() -> list[dict[str, Any]]:
        from ffbb_data_client.config import (
            MEILISEARCH_INDEX_COMPETITIONS,
            MEILISEARCH_INDEX_ORGANISMES,
            MEILISEARCH_INDEX_PRATIQUES,
            MEILISEARCH_INDEX_RENCONTRES,
            MEILISEARCH_INDEX_SALLES,
            MEILISEARCH_INDEX_TERRAINS,
            MEILISEARCH_INDEX_TOURNOIS,
        )
        from ffbb_data_client.models import MultiSearchQuery

        client = await get_client_async()
        primary_limit = min(limit, max(2, (limit + 2) // 3))
        secondary_limit = min(limit, max(1, (limit + 9) // 10))
        queries = [
            MultiSearchQuery(
                index_uid=MEILISEARCH_INDEX_ORGANISMES,
                q=normalized_query,
                limit=primary_limit,
            ),
            MultiSearchQuery(
                index_uid=MEILISEARCH_INDEX_COMPETITIONS,
                q=normalized_query,
                limit=primary_limit,
            ),
            MultiSearchQuery(
                index_uid=MEILISEARCH_INDEX_RENCONTRES,
                q=normalized_query,
                limit=primary_limit,
            ),
            MultiSearchQuery(
                index_uid=MEILISEARCH_INDEX_SALLES,
                q=normalized_query,
                limit=secondary_limit,
            ),
            MultiSearchQuery(
                index_uid=MEILISEARCH_INDEX_PRATIQUES,
                q=normalized_query,
                limit=secondary_limit,
            ),
            MultiSearchQuery(
                index_uid=MEILISEARCH_INDEX_TERRAINS,
                q=normalized_query,
                limit=secondary_limit,
            ),
            MultiSearchQuery(
                index_uid=MEILISEARCH_INDEX_TOURNOIS,
                q=normalized_query,
                limit=secondary_limit,
            ),
        ]

        raw = await _with_ffbb_semaphore(
            _safe_call_with_inflight(
                f"Multi-search: {nom}", lambda: client.multi_search_async(queries)
            )
        )

        if not getattr(raw, "results", None):
            return []

        output: list[dict[str, Any]] = []
        total_hits = 0
        for res in raw.results:
            category = res.index_uid
            est = getattr(res, "estimated_total_hits", None)
            if est is not None:
                total_hits += est
            for hit in res.hits:
                item = serialize_model(hit)
                item["_type"] = category
                output.append(item)
                if len(output) >= limit:
                    if total_hits > len(output):
                        for out_item in output:
                            out_item["_total_hits"] = total_hits
                    return output
        return output

    return await _dedupe_inflight(
        cache=state.cache_search,
        cache_key=cache_key,
        inflight_map=state.inflight_search,
        make_coro=_fetch,
        cache_name="search",
    )


def _add_truncation_meta(result: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ajoute un objet _meta en tête de liste si les résultats sont tronqués."""
    if not result:
        return result
    total = result[0].pop("_total_hits", None)
    for item in result[1:]:
        item.pop("_total_hits", None)
    if total is not None and total > len(result):
        result.insert(
            0,
            {
                "_meta": True,
                "total": total,
                "returned": len(result),
                "truncated": True,
                "message": (
                    f"{total} résultats trouvés, {len(result)} retournés. "
                    "Utilisez ffbb_club(action='calendrier') pour les données complètes."
                ),
            },
        )
    return result


async def ffbb_search_service(
    *,
    type: str = "all",
    query: str,
    limit: int = 20,
    filter_by: str | None = None,
    sort: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Service de recherche FFBB.

    Recherche dans les données FFBB en fonction de plusieurs types de données.
    """
    if type == "all":
        result = await multi_search_service(nom=query, limit=limit)
        if not isinstance(result, list):
            return []
        return _add_truncation_meta(result)

    if type == "organismes":
        result = await search_organismes_service(query, limit, filter_by, sort)
        return _add_truncation_meta(result)

    if method_name := _SEARCH_TYPE_METHOD.get(type):
        result = await _search_generic(type, method_name, query, limit, filter_by, sort)
        return _add_truncation_meta(result)

    raise McpError(
        error=ErrorData(
            code=INTERNAL_ERROR,
            message=f"Type de recherche inconnu: {type}",
        )
    )


async def ffbb_resolve_team_service(
    *,
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
) -> dict[str, Any]:
    """Résout une équipe unique d'un club pour une catégorie donnée.

    Retourne un objet structuré pour les agents :
      - `status`: "resolved" | "ambiguous" | "not_found"
      - `team`: équipe résolue (ou None si ambiguë / introuvable)
      - `candidates`: liste des équipes candidates (peut être vide)
      - `ambiguity`: message explicite en cas d'ambiguïté
    """
    import ffbb_mcp.services

    if not club_name and not organisme_id:
        raise McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message="Fournir club_name ou organisme_id",
            )
        )

    if not categorie:
        raise McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message="Paramètre 'categorie' requis (ex: 'U11M1', 'U13F2').",
            )
        )

    # 1) Résoudre l'organisme avec métadonnées
    resolved_clubs, _ = await resolve_club_and_org(
        club_name=club_name, organisme_id=organisme_id, categorie=categorie
    )

    if not resolved_clubs:
        return {
            "status": "not_found",
            "team": None,
            "candidates": [],
            "ambiguity": f"Club '{club_name or organisme_id}' introuvable",
            "club_resolu": None,
        }

    # Si ambiguïté club
    if len(resolved_clubs) > 1 and not organisme_id:
        return {
            "status": "ambiguous",
            "team": None,
            "candidates": resolved_clubs,
            "ambiguity": f"Plusieurs clubs correspondent à '{club_name}'.",
            "club_resolu": None,
        }

    club_resolu = resolved_clubs[0]
    target_org_id = str(club_resolu["organisme_id"])

    # 2) Récupérer toutes les équipes candidates
    equipes = await ffbb_mcp.services.ffbb_equipes_club_service(
        organisme_id=target_org_id, filtre=categorie
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
            "club_resolu": club_resolu,
        }

    # 3) Matching intelligent du numéro
    candidates = equipes
    parsed = parse_categorie(categorie)
    target_num = str(parsed.numero_equipe) if parsed.numero_equipe else None

    # On cherche d'abord le numéro exact, fallback sur équipe sans numéro
    matched = _resolve_team_number(candidates, target_num)
    if matched:
        candidates = matched

    # 3.5) Déduplication sémantique : même équipe à travers différentes phases
    candidates = _deduplicate_same_team_phases(candidates)

    # 4) Construire la réponse
    if not candidates:
        all_labels = sorted(list({t["team_label"] for t in equipes}))
        return {
            "status": "not_found",
            "team": None,
            "candidates": all_labels,
            "ambiguity": f"Aucun match exact pour '{categorie}'",
            "club_resolu": club_resolu,
        }

    if len(candidates) == 1:
        return {
            "status": "resolved",
            "team": candidates[0],
            "candidates": candidates,
            "ambiguity": None,
            "club_resolu": club_resolu,
        }

    # Si on a plusieurs candidats, on vérifie s'ils partagent tous le même numero_equipe.
    unique_nums = {str(c.get("numero_equipe") or "").strip() for c in candidates}

    if len(unique_nums) == 1:
        best = max(candidates, key=_phase_sort_key)
        return {
            "status": "resolved",
            "team": best,
            "candidates": candidates,
            "ambiguity": None,
            "club_resolu": club_resolu,
        }

    return {
        "status": "ambiguous",
        "team": None,
        "candidates": candidates,
        "ambiguity": f"Plusieurs équipes ({len(candidates)}) correspondent à '{categorie}'.",
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
    if not equipes:
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
