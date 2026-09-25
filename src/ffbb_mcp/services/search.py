from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache
from typing import Any, Protocol, cast

import httpx
from mcp.types import INTERNAL_ERROR, ErrorData
from pydantic import ValidationError

from ffbb_mcp._state import state

from .common import (
    McpError,
    _coerce_numeric_id,
    _dedupe_inflight,
    _extract_phase_num,
    _is_entente_name,
    _normalize_name,
    _safe_call_with_inflight,
    _with_ffbb_semaphore,
)


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

from .salle import _enrich_with_salle_details

logger = logging.getLogger("ffbb-mcp")

_NUMERIC_EXTRACT_PATTERN = re.compile(r"(\d+)")


from .team_resolver import (
    _deduplicate_same_team_phases,
    _determine_niveau_label,
    _dump_resolution_without_candidates,
    _extract_base_competition_name,
    _is_coupe_competition,
    _phase_sort_key,
    ffbb_find_team_candidates_service,
    ffbb_resolve_team_service,
)

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
    "news": "search_news",
    "galeries": "search_galeries",
    "rss": "search_rss",
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
        nom = ent_org.get("nom", "")
        nom_norm = _normalize_name(str(nom))
        # Inclure uniquement les ententes (nom désignant une entente / CTC)
        # qui contiennent le mot-clé distinctif du club recherché.
        if _is_entente_name(nom) and key_word_norm in nom_norm:
            additions.append(_build_club_candidate(ent_org, nom))
            existing_ids.add(oid)
            logger.debug("ffbb_resolve: entente candidate détectée")

    return additions


async def filter_inactive_ententes(
    items: list[dict[str, Any]],
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Exclut les ententes ou CTC n'ayant aucune équipe engagée dans la saison en cours.

    Préserve immédiatement les clubs normaux (non-ententes) sans coût réseau.
    Pour les ententes détectées (_is_entente_name), vérifie asynchronement
    l'existence d'équipes actives via ffbb_equipes_club_service.
    """
    if not items:
        return items

    entente_oids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        nom = str(item.get("nom") or item.get("libelle") or "")
        if _is_entente_name(nom):
            oid = str(item.get("organisme_id") or item.get("id") or "").strip()
            if oid:
                entente_oids.add(oid)

    if not entente_oids:
        return items

    from .club import ffbb_equipes_club_service

    async def _check_active(oid: str) -> tuple[str, bool]:
        try:
            equipes = await ffbb_equipes_club_service(
                organisme_id=oid,
                force_refresh=force_refresh,
            )
            is_active = bool(
                equipes
                and isinstance(equipes, list)
                and not (len(equipes) == 1 and equipes[0].get("error"))
            )
            return oid, is_active
        except Exception:
            logger.debug(
                "Erreur lors de la vérification des équipes d'une entente",
                exc_info=True,
            )
            return oid, False

    results = await asyncio.gather(*[_check_active(oid) for oid in entente_oids])
    active_map = dict(results)

    filtered: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        nom = str(item.get("nom") or item.get("libelle") or "")
        oid = str(item.get("organisme_id") or item.get("id") or "").strip()
        if _is_entente_name(nom) and not active_map.get(oid, False):
            logger.debug("Entente inactive exclue (0 équipe engagée)")
            continue
        filtered.append(item)

    return filtered


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


async def _search_organismes_directus(
    query: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Recherche des organismes directement via l'API Directus de la FFBB.

    Permet de contourner les lacunes de l'index Meilisearch (ex: organisme 10948 Andrézieux)
    et supporte la recherche par code FFBB (ex: ARA0042016), acronymes et sous-chaînes.
    """
    client = await get_client_async()
    api = getattr(client, "_api", None)
    if not api:
        return []
    base = getattr(api, "url", "https://api.ffbb.app").rstrip("/")
    headers = getattr(api, "headers", {})

    q_clean = query.strip()
    if not q_clean:
        return []

    is_code = bool(re.match(r"^[A-Za-z]{2,4}\d{4,9}$", q_clean))
    from ffbb_mcp.aliases import resolve_acronym

    resolved_acronym = resolve_acronym(q_clean)

    queries_to_try: list[tuple[str, str]] = []
    if is_code:
        queries_to_try.append(("code", q_clean))
    queries_to_try.append(("search", q_clean))
    if resolved_acronym != q_clean:
        queries_to_try.append(("search", resolved_acronym))

    # Mots clés distinctifs (sans stop-words et sans mots géographiques génériques)
    cleaned = re.sub(r"[^\w\s]", " ", q_clean).strip()
    words = cleaned.split()
    tokens = [
        w
        for w in words
        if len(w) >= 4
        and w.upper() not in _GENERIC_CLUB_WORDS
        and w.upper() not in {"LOIRE", "SUD", "NORD", "EST", "OUEST", "SAINT", "SAINTE"}
    ]
    for tok in tokens:
        queries_to_try.append(("nom_icontains", tok))

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    fields_param = "fields[]=id,nom,code,commune.libelle,commune.codePostal,logo.id,logo.gradient_color"

    session = getattr(api, "async_cached_session", None)

    for q_type, q_val in queries_to_try:
        if len(results) >= limit:
            break
        if q_type == "code":
            url = f"{base}/items/ffbbserver_organismes?filter[code][_icontains]={q_val}&{fields_param}&limit={limit}"
        elif q_type == "nom_icontains":
            url = f"{base}/items/ffbbserver_organismes?filter[nom][_icontains]={q_val}&{fields_param}&limit={limit}"
        else:
            url = f"{base}/items/ffbbserver_organismes?search={q_val}&{fields_param}&limit={limit}"

        try:
            if session:
                resp = await session.get(url, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=8.0) as http:
                    resp = await http.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if isinstance(data, list):
                    for item in data:
                        oid = str(item.get("id"))
                        if oid and oid not in seen_ids:
                            seen_ids.add(oid)
                            results.append(item)
        except Exception as e:
            logger.debug(
                "Erreur requête directus organismes (%s, %s): %s",
                q_type,
                q_val,
                e,
            )

    return results


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

        # Fallback Directus si Meilisearch n'a trouvé aucun match confiant
        from ffbb_mcp.services.common import is_club_match_confident

        has_confident_org = any(is_club_match_confident(o, club_name) for o in orgs)
        if not orgs or not has_confident_org:
            directus_orgs = await _search_organismes_directus(club_name, limit=limit)
            if directus_orgs:
                existing_org_ids = {str(o.get("id")) for o in orgs}
                new_directus = [
                    o for o in directus_orgs if str(o.get("id")) not in existing_org_ids
                ]
                orgs = new_directus + orgs

        # Application du Smart Resolution M/F
        if categorie:
            orgs = _filter_orgs_by_gender(orgs, categorie, club_name)

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

        # Filtrage automatique des ententes inactives (0 équipe active engagée cette saison)
        # pour éliminer d'office les coquilles vides fantômes des candidats et suggestions.
        if any(_is_entente_name(c.get("nom")) for c in resolved):
            resolved = await filter_inactive_ententes(
                resolved, force_refresh=force_refresh
            )

        # Jaro-Winkler Sorting Optimization avec priorité absolue au match exact
        if len(resolved) > 1 and club_name:
            resolved.sort(
                key=lambda c: (
                    2.0
                    if _normalize_name(c.get("nom", "")) == norm_club_name
                    or str(c.get("code", "")).upper() == club_name.upper().strip()
                    else jaro_winkler_similarity(club_name, c["nom"])
                ),
                reverse=True,
            )

        # Garde-fou anti-hallucination : ne conserver que les candidats ayant une correspondance crédible
        if resolved and club_name:
            confident_resolved = [
                c for c in resolved if is_club_match_confident(c, club_name)
            ]
            resolved = confident_resolved

        if resolved:
            # On récupère le détail du premier club résolu pour avoir les métadonnées riches
            try:
                first_org_id = resolved[0].get("organisme_id")
                if first_org_id:
                    org_data = await ffbb_mcp.services.get_organisme_service(
                        first_org_id, force_refresh=force_refresh
                    )
            except (httpx.HTTPError, McpError, ValidationError):
                logger.debug(
                    "Impossible de charger les détails du premier organisme pour %s",
                    club_name,
                    exc_info=True,
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


_GENERIC_SEARCH_TERMS = {
    "",
    "basket",
    "basketball",
    "club",
    "clubs",
    "tous",
    "all",
    "ffbb",
}


def _rewrite_filter_for_index(filter_by: str | None, type_name: str) -> str | None:
    """Réécrit les alias de champs utilisateur/doc vers les vrais attributs Meilisearch.

    Ex: 'codePostal = "45560"' -> 'commune.codePostal = "45560"' pour organismes/salles.
    """
    if not filter_by:
        return None
    s = filter_by
    if type_name in {
        "organismes",
        "rencontres",
        "salles",
        "terrains",
        "tournois",
        "engagements",
    }:
        s = re.sub(
            r"(?<!commune\.)(?<!communeClubPro\.)\bcodePostal\b",
            "commune.codePostal",
            s,
        )
        s = re.sub(
            r"(?<!commune\.)(?<!communeClubPro\.)\bdepartement\b",
            "commune.departement",
            s,
        )
        s = re.sub(
            r"(?<!commune\.)(?<!communeClubPro\.)\bville\b",
            "commune.libelle",
            s,
        )
    elif type_name == "formations":
        s = re.sub(r"\bcodePostal\b", "postal_code", s)
        s = re.sub(r"\bville\b", "place", s)
    return s


def _rewrite_sort_for_index(sort: list[str] | None, type_name: str) -> list[str] | None:
    """Réécrit les alias de tri vers les attributs triables de l'index Meilisearch."""
    if not sort:
        return None
    rewritten: list[str] = []
    for s in sort:
        if type_name in {
            "organismes",
            "salles",
            "terrains",
            "tournois",
            "engagements",
        }:
            s = re.sub(
                r"(?<!commune\.)(?<!communeClubPro\.)\bcodePostal\b",
                "commune.codePostal",
                s,
            )
            s = re.sub(
                r"(?<!commune\.)(?<!communeClubPro\.)\bville\b",
                "commune.libelle",
                s,
            )
        if type_name == "salles":
            s = re.sub(r"\bnom:", "libelle:", s)
        rewritten.append(s)
    return rewritten


def _lighten_competition_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Allège un résultat de recherche de compétition pour limiter l'empreinte réseau/tokens.

    Supprime les listes d'engagements imbriquées dans chaque poule et les listes
    lourdes dupliquées dans organisateur (accessibles exhaustivement via ffbb_get).
    """
    if not isinstance(hit, dict):
        return hit
    item = dict(hit)
    if "organisateur" in item and isinstance(item["organisateur"], dict):
        org = item["organisateur"]
        item["organisateur"] = {
            "id": org.get("id"),
            "nom": org.get("nom"),
            "code": org.get("code"),
            "type": org.get("type"),
        }
    if "poules" in item and isinstance(item["poules"], list):
        item["poules"] = [
            {"id": p.get("id"), "nom": p.get("nom")}
            for p in item["poules"]
            if isinstance(p, dict)
        ]
    return item


def _build_search_results(
    results: Any, limit: int, offset: int = 0, type_name: str | None = None
) -> list[dict]:
    """Construit la liste de résultats et attache _total_hits si pagination/troncature."""
    if not results or not getattr(results, "hits", None):
        return []
    raw_hits = results.hits
    if offset and len(raw_hits) > offset:
        raw_hits = raw_hits[offset : offset + limit]
    else:
        raw_hits = raw_hits[:limit]
    result_list = [serialize_model(hit) for hit in raw_hits]
    if type_name == "competitions":
        result_list = [_lighten_competition_hit(hit) for hit in result_list]
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
    safe_filter = _rewrite_filter_for_index(filter_by, type_name)
    safe_sort = _rewrite_sort_for_index(sort, type_name)

    filter_part = safe_filter or ""
    sort_part = ",".join(safe_sort) if safe_sort else ""
    cache_key = f"search:{type_name}:{normalized_query}:{limit}:{offset}:{filter_part}:{sort_part}"

    async def _fetch() -> list[dict[str, Any]]:
        client = await get_client_async()

        # Si une méthode de recherche directe existe sur le client (ex: search_organismes_async)
        # Note: on ne délègue à direct_method que si elle supporte les filtres/tris/offsets demandés
        method_name = _SEARCH_TYPE_METHOD.get(type_name)
        direct_method: Any = getattr(client, method_name, None) if method_name else None
        can_use_direct = offset == 0
        if direct_method and callable(direct_method) and can_use_direct:
            try:
                import inspect

                sig = inspect.signature(direct_method)
                params = sig.parameters
                call_kwargs: dict[str, Any] = {}

                if "name" in params:
                    call_kwargs["name"] = query
                elif "nom" in params:
                    call_kwargs["nom"] = query
                elif len(params) > 0:
                    first_param = next(iter(params.values()))
                    if first_param.kind in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    ):
                        call_kwargs[first_param.name] = query

                if "limit" in params:
                    call_kwargs["limit"] = limit

                filter_list = [safe_filter] if safe_filter else None
                if safe_filter:
                    if "filter" in params:
                        call_kwargs["filter"] = filter_list
                    else:
                        can_use_direct = False

                if safe_sort:
                    if "sort" in params:
                        call_kwargs["sort"] = safe_sort
                    else:
                        can_use_direct = False

                if can_use_direct:

                    async def _invoke_direct() -> Any:
                        res: Any = direct_method(**call_kwargs)
                        if inspect.isawaitable(res):
                            return await res  # type: ignore[no-any-return]
                        return res

                    direct_res = await _with_ffbb_semaphore(
                        _safe_call_with_inflight(
                            f"Search direct {type_name}: {query}",
                            _invoke_direct,
                        )
                    )
                    if (
                        direct_res is not None
                        and getattr(direct_res, "hits", None) is not None
                        and len(direct_res.hits) > 0
                    ):
                        return _build_search_results(
                            direct_res, limit, offset, type_name=type_name
                        )
            except Exception as e:
                logger.debug(
                    "Échec recherche directe %s, repli Meilisearch: %s",
                    type_name,
                    e,
                )

        index_uid = _SEARCH_INDEX_MAP.get(type_name, type_name)
        filter_list = [safe_filter] if safe_filter else None
        search_q = normalized_query
        if safe_filter and normalize_query(query) in _GENERIC_SEARCH_TERMS:
            # Si le filtre est actif et la requête est un terme générique (ex: "basket"),
            # Meilisearch ne matcherait pas les clubs dont le nom ne contient pas ce terme.
            # On cherche avec q="" pour laisser le filtre opérer pleinement.
            search_q = ""

        q = [
            MultiSearchQuery(
                index_uid=index_uid,
                q=search_q,
                limit=limit,
                offset=offset,
                filter=filter_list,
                sort=safe_sort,
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
            if safe_filter and search_q and "" not in fallbacks:
                fallbacks.append("")
            for fb in fallbacks:
                if fb == query or (not fb and not search_q):
                    continue
                q_fb = [
                    MultiSearchQuery(
                        index_uid=index_uid,
                        q=normalize_query(fb) if fb else "",
                        limit=limit,
                        offset=offset,
                        filter=filter_list,
                        sort=safe_sort,
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
        if type_name == "competitions":
            hits = [_lighten_competition_hit(h) for h in hits]
        total_val = getattr(res0, "estimated_total_hits", None)
        if total_val is not None:
            try:
                total = int(total_val)
            except (TypeError, ValueError):
                total = len(hits)
        else:
            total = len(hits)

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


def _score_organisme_relevance(r: dict[str, Any], query: str) -> float:
    """Calcule un score de pertinence pour classer un organisme par rapport à la requête.

    Priorise les correspondances exactes/partielles sur la commune et le nom du club.
    """
    q_norm = _normalize_name(query)
    if not q_norm:
        return 0.0
    nom_val = _normalize_name(r.get("nom", ""))
    commune_obj = r.get("commune")
    commune_val = _normalize_name(
        commune_obj.get("libelle", "")
        if isinstance(commune_obj, dict)
        else (str(commune_obj) if commune_obj else "")
    )
    code_val = str(r.get("code", "")).upper().strip()

    # Match exact prioritaire sur le code club ou le nom
    if code_val and code_val == query.upper().strip():
        return 200.0
    if q_norm == nom_val:
        return 100.0

    score = 0.0
    if q_norm in nom_val:
        score += 60.0
    elif nom_val in q_norm and len(nom_val) >= 4:
        score += 30.0

    if q_norm == commune_val:
        score += 80.0
    elif q_norm in commune_val:
        score += 50.0
    elif commune_val and commune_val in q_norm:
        score += 30.0

    score += jaro_winkler_similarity(q_norm, nom_val) * 10.0
    if commune_val:
        score += jaro_winkler_similarity(q_norm, commune_val) * 10.0

    q_words = set(q_norm.split())
    target_words = set(nom_val.split()) | set(commune_val.split())
    if q_words:
        score += (len(q_words & target_words) / len(q_words)) * 15.0

    return score


async def search_organismes_service(
    nom: str,
    limit: int = 20,
    offset: int = 0,
    filter_by: str | None = None,
    sort: list[str] | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    results = await _search_generic(
        "organismes",
        nom,
        limit=limit,
        offset=offset,
        filter_by=filter_by,
        sort=sort,
        force_refresh=force_refresh,
    )
    from ffbb_mcp.services.common import is_club_match_confident

    q_clean = nom.strip()
    is_code = bool(re.match(r"^[A-Za-z]{2,4}\d{4,9}$", q_clean))
    has_confident = (
        any(is_club_match_confident(r, nom) for r in results) if results else False
    )
    if (
        not filter_by
        and not sort
        and (not results or is_code or not has_confident or len(results) < limit)
    ):
        directus_results = await _search_organismes_directus(nom, limit=limit)
        if directus_results:
            existing_ids = {str(r.get("id") or r.get("organisme_id")) for r in results}
            for d_item in directus_results:
                d_id = str(d_item.get("id"))
                if d_id not in existing_ids:
                    existing_ids.add(d_id)
                    results.insert(0, d_item)

    if results and any(_is_entente_name(o.get("nom")) for o in results):
        results = await filter_inactive_ententes(results, force_refresh=force_refresh)

    # Réordonnancement de pertinence si aucun tri explicite n'a été demandé
    if results and not sort:
        results.sort(
            key=lambda r: _score_organisme_relevance(r, nom),
            reverse=True,
        )

    return results


def _build_multi_search_queries(
    active_indexes: list[str],
    normalized_query: str,
    limit: int,
    filter_by: str | None = None,
    sort: list[str] | None = None,
) -> list[Any]:
    from ffbb_data_client.models import MultiSearchQuery

    primary_limit = min(limit, max(2, (limit + 2) // 3))
    secondary_limit = min(limit, max(1, (limit + 9) // 10))

    inv_map = {v: k for k, v in _SEARCH_INDEX_MAP.items()}

    queries: list[Any] = []
    for idx in active_indexes:
        type_name = inv_map.get(
            idx, idx.replace("ffbbserver_", "").replace("ffbbsite_", "")
        )
        idx_filter = (
            _rewrite_filter_for_index(filter_by, type_name) if filter_by else None
        )
        if (
            idx_filter
            and "commune." in idx_filter
            and type_name in ("competitions", "formations", "news", "galeries", "rss")
        ):
            continue

        idx_sort = _rewrite_sort_for_index(sort, type_name) if sort else None
        search_q = normalized_query
        if idx_filter and normalized_query in _GENERIC_SEARCH_TERMS:
            search_q = ""

        queries.append(
            MultiSearchQuery(
                index_uid=idx,
                q=search_q,
                limit=primary_limit
                if idx in _PRIMARY_SEARCH_INDEXES
                else secondary_limit,
                filter=[idx_filter] if idx_filter else None,
                sort=idx_sort,
            )
        )
    return queries or [
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
    filter_by: str | None = None,
    sort: list[str] | None = None,
) -> Any:
    """Exécute un multi-search Meilisearch avec auto-découverte et boucle de self-healing."""
    from ffbb_data_client.models import MultiSearchQuery

    if state.active_search_indexes is None:
        # Résolution dynamique initiale via discovery
        try:
            from ffbb_data_client.data import load_discovery_artefact

            disc = load_discovery_artefact("indexes.json")
            available = set(disc.get("available_indexes") or [])
            if available:
                state.active_search_indexes = [
                    idx for idx in _ALL_CANDIDATE_SEARCH_INDEXES if idx in available
                ]
        except Exception:
            pass

        if not state.active_search_indexes:
            state.active_search_indexes = list(_ALL_CANDIDATE_SEARCH_INDEXES)

    active_indexes = list(state.active_search_indexes)
    queries = _build_multi_search_queries(
        active_indexes, normalized_query, limit, filter_by=filter_by, sort=sort
    )

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
            healthy_indexes, normalized_query, limit, filter_by=filter_by, sort=sort
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
    filter_by: str | None = None,
    sort: list[str] | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    normalized_query = normalize_query(nom)
    filter_part = filter_by or ""
    sort_part = ",".join(sort) if sort else ""
    cache_key = (
        f"multi_search:{normalized_query}:{limit}:{offset}:{filter_part}:{sort_part}"
    )

    async def _fetch() -> list[dict[str, Any]]:
        client = await get_client_async()
        # Pour supporter l'offset, on fetch offset+limit puis on slice côté MCP
        fetch_limit = offset + limit if offset else limit
        raw = await _execute_multi_search_with_self_healing(
            client=client,
            nom=nom,
            normalized_query=normalized_query,
            limit=fetch_limit,
            filter_by=filter_by,
            sort=sort,
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
                if "competitions" in category:
                    item = _lighten_competition_hit(item)
                item["_type"] = category
                output.append(item)
                if len(output) >= fetch_limit:
                    break
            if len(output) >= fetch_limit:
                break

        # Filtrage automatique des ententes inactives parmi les hits d'organismes
        if any(
            item.get("_type") == "organismes" and _is_entente_name(item.get("nom"))
            for item in output
        ):
            org_items = [item for item in output if item.get("_type") == "organismes"]
            active_orgs = await filter_inactive_ententes(
                org_items, force_refresh=force_refresh
            )
            active_ids = {
                str(o.get("id") or o.get("organisme_id")) for o in active_orgs
            }
            output = [
                item
                for item in output
                if item.get("_type") != "organismes"
                or str(item.get("id") or item.get("organisme_id")) in active_ids
            ]

        # Fallback Directus si aucun organisme confiant n'a été trouvé par Meilisearch
        from ffbb_mcp.services.common import is_club_match_confident

        has_org_match = any(
            item.get("_type") == "organismes" and is_club_match_confident(item, nom)
            for item in output
        )
        q_clean = nom.strip()
        is_code = bool(re.match(r"^[A-Za-z]{2,4}\d{4,9}$", q_clean))
        if not has_org_match or is_code:
            directus_orgs = await _search_organismes_directus(nom, limit=min(5, limit))
            if directus_orgs:
                existing_ids = {
                    str(item.get("id") or item.get("organisme_id"))
                    for item in output
                    if item.get("_type") == "organismes"
                }
                for d_item in directus_orgs:
                    d_id = str(d_item.get("id"))
                    if d_id not in existing_ids:
                        existing_ids.add(d_id)
                        d_copy = dict(d_item)
                        d_copy["_type"] = "organismes"
                        output.insert(0, d_copy)

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
    sort: list[str] | None = None,
) -> dict[str, Any]:
    """Enveloppe le résultat de recherche avec des métadonnées de pagination.

    Retourne un dict ``{"items": [...], "_meta": {...}}`` au lieu d'une liste brute.
    """
    sort_str = ",".join(sort) if sort else "relevance:desc"
    if not result:
        return {
            "items": [],
            "_meta": {
                "total": 0,
                "returned": 0,
                "limit": limit,
                "offset": offset,
                "has_more": False,
                "sort": sort_str,
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
        "sort": sort_str,
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
            nom=query,
            limit=limit,
            offset=offset,
            filter_by=filter_by,
            sort=sort,
            force_refresh=force_refresh,
        )
        if not isinstance(result, list):
            return []
        # multi_search_service déjà slice, mais on garde offset meta cohérente
        return _add_truncation_meta(result, limit=limit, offset=offset, sort=sort)

    if type == "organismes":
        result = await search_organismes_service(
            query,
            limit=limit,
            offset=offset,
            filter_by=filter_by,
            sort=sort,
            force_refresh=force_refresh,
        )
        return _add_truncation_meta(result, limit=limit, offset=offset, sort=sort)

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
        return _add_truncation_meta(result, limit=limit, offset=offset, sort=sort)

    from mcp.types import INVALID_PARAMS

    if type == "communes":
        raise McpError(
            error=ErrorData(
                code=INVALID_PARAMS,
                message=(
                    "Pour rechercher par commune ou ville, utilisez type='organismes' ou type='salles' "
                    "avec filter_by='commune.libelle = \"...\"' ou filter_by='commune.codePostal = \"...\"'."
                ),
            )
        )

    if type in ("officiels", "entraineurs"):
        raise McpError(
            error=ErrorData(
                code=INVALID_PARAMS,
                message=(
                    f"La recherche textuelle multi-critères n'est pas disponible pour '{type}' (aucun index Meilisearch public). "
                    f"Utilisez ffbb_get(type='{type[:-1]}', id=...) pour consulter une fiche par son identifiant."
                ),
            )
        )

    raise McpError(
        error=ErrorData(
            code=INTERNAL_ERROR,
            message=f"Type de recherche inconnu: {type}. Types supportés: {', '.join(['all', *list(_SEARCH_INDEX_MAP.keys())])}",
        )
    )


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


__all__ = [
    "_deduplicate_same_team_phases",
    "_determine_niveau_label",
    "_dump_resolution_without_candidates",
    "_extract_base_competition_name",
    "_extract_club_key_word",
    "_is_coupe_competition",
    "_phase_sort_key",
    "ffbb_find_team_candidates_service",
    "ffbb_resolve_team_service",
    "ffbb_search_service",
    "filter_inactive_ententes",
    "get_asset_url_service",
    "get_client_async",
    "get_entraineur_service",
    "get_officiel_service",
    "get_rencontre_service",
    "multi_search_service",
    "resolve_club_and_org",
    "resolve_poule_id_service",
    "search_organismes_service",
]
