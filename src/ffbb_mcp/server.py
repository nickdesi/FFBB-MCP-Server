"""
FFBB MCP Server — Serveur MCP pour les données de la Fédération Française de Basketball.

Expose des outils MCP pour accéder aux données FFBB :
- Matchs en direct
- Compétitions, poules, saisons
- Clubs/organismes, salles
- Recherche multi-types (compétitions, clubs, rencontres, salles, pratiques, terrains, tournois)

Architecture :
- Lifespan : initialisation unique du client FFBB au démarrage
- Context  : logging MCP et signalement de progression
- Error handling : messages d'erreur spécifiques (404, 403, 429, timeout)
- json_response : sorties JSON structurées
- Annotations : readOnlyHint, idempotentHint, openWorldHint sur chaque tool
- Pydantic : validation des inputs via BaseModel
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import BaseModel, ConfigDict, Field

from ffbb_api_client_v3 import FFBBAPIClientV3
from ffbb_api_client_v3.helpers.multi_search_query_helper import generate_queries

from ffbb_mcp.client import get_client
from ffbb_mcp.utils import serialize_model

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ffbb-mcp")


# ---------------------------------------------------------------------------
# Pydantic Input Models
# ---------------------------------------------------------------------------
class SearchInput(BaseModel):
    """Paramètres de recherche FFBB."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(
        ...,
        description="Terme de recherche (ex: 'Vichy', 'Pro B', 'Astroballe')",
        min_length=1,
        max_length=200,
    )


class CompetitionIdInput(BaseModel):
    """Identifiant d'une compétition FFBB."""

    model_config = ConfigDict(extra="forbid")

    competition_id: int = Field(
        ...,
        description="ID numérique de la compétition (obtenu via ffbb_search_competitions)",
        ge=1,
    )


class PouleIdInput(BaseModel):
    """Identifiant d'une poule/groupe."""

    model_config = ConfigDict(extra="forbid")

    poule_id: int = Field(
        ...,
        description="ID numérique de la poule (obtenu via ffbb_get_competition)",
        ge=1,
    )


class OrganismeIdInput(BaseModel):
    """Identifiant d'un organisme/club FFBB."""

    model_config = ConfigDict(extra="forbid")

    organisme_id: int = Field(
        ...,
        description="ID numérique de l'organisme (obtenu via ffbb_search_organismes)",
        ge=1,
    )


class SaisonsInput(BaseModel):
    """Paramètres de récupération des saisons."""

    model_config = ConfigDict(extra="forbid")

    active_only: bool = Field(
        default=False,
        description="Si True, retourne uniquement les saisons actives",
    )


class CalendrierClubInput(BaseModel):
    """Paramètres pour récupérer le calendrier d'un club."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    club_name: str = Field(
        ...,
        description="Nom du club (ex: 'Stade Clermontois', 'ASVEL')",
        min_length=1,
        max_length=200,
    )
    categorie: str = Field(
        default="",
        description="Catégorie optionnelle (ex: 'U11M', 'Seniors F', 'U13F')",
        max_length=50,
    )


# ---------------------------------------------------------------------------
# Lifespan — typed application context
# ---------------------------------------------------------------------------
@dataclass
class FFBBContext:
    """Contexte applicatif typé injecté dans chaque tool via ctx.app_context."""

    client: FFBBAPIClientV3


@asynccontextmanager
async def ffbb_lifespan(server: FastMCP) -> AsyncIterator[FFBBContext]:
    """Initialise le client FFBB une seule fois au démarrage du serveur."""
    logger.info("Initialisation du client FFBB via lifespan...")
    client = get_client()
    logger.info("Client FFBB prêt.")
    try:
        yield FFBBContext(client=client)
    finally:
        logger.info("Arrêt du serveur MCP FFBB.")


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="ffbb_mcp",
    instructions=(
        "Ce serveur expose les données de la Fédération Française de Basketball "
        "(FFBB). "
        "Tu peux consulter les matchs en direct, le calendrier des rencontres, "
        "les résultats, les compétitions, les clubs et les salles de sport.\n\n"
        "Workflow recommandé :\n"
        "1. Utilise `ffbb_multi_search` pour une exploration générale\n"
        "2. Ou `ffbb_search_*` pour cibler un type précis "
        "(compétitions, clubs, matchs, salles, pratiques, terrains, tournois)\n"
        "3. Puis `ffbb_get_*` avec l'ID obtenu pour les détails complets\n\n"
        "Tous les outils renvoient du JSON structuré."
    ),
    lifespan=ffbb_lifespan,
    json_response=True,
)

# Type alias for the context used in tools
Ctx = Context[ServerSession, FFBBContext]

# Read-only annotations (all FFBB tools are read-only)
_READONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------
def _handle_api_error(e: Exception) -> str:
    """Formatage cohérent des erreurs API pour tous les outils."""
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 404:
            return "Erreur : Ressource introuvable. Vérifiez l'ID fourni."
        if status == 403:
            return "Erreur : Accès refusé. Ce endpoint nécessite des permissions spécifiques."
        if status == 429:
            return "Erreur : Limite de requêtes dépassée. Réessayez dans quelques instants."
        return f"Erreur : L'API FFBB a retourné le code {status}."
    if isinstance(e, httpx.TimeoutException):
        return "Erreur : Délai d'attente dépassé. Réessayez."
    return f"Erreur : {type(e).__name__} — {e}"


async def _safe_call(ctx: Ctx, operation: str, coro) -> Any:
    """Exécute un appel API avec logging MCP et error handling spécifique."""
    try:
        await ctx.info(f"🔍 {operation}...")
        result = await coro
        return result
    except Exception as e:
        msg = _handle_api_error(e)
        await ctx.error(f"❌ {msg}")
        logger.exception(f"Erreur: {operation}")
        return None


# ---------------------------------------------------------------------------
# Outils MCP — Données en direct
# ---------------------------------------------------------------------------

@mcp.tool(
    name="ffbb_get_lives",
    annotations=_READONLY_ANNOTATIONS,
    description=(
        "Récupère les matchs de basketball en cours (live). "
        "Retourne la liste des rencontres avec les scores actuels, "
        "les équipes et le statut du match."
    ),
)
async def ffbb_get_lives(ctx: Ctx) -> list[dict[str, Any]]:
    """Matchs en cours (scores live).

    Returns:
        list[dict]: Liste de matchs en direct. Chaque dict contient :
            - equipe1 (str): Nom de l'équipe domicile
            - equipe2 (str): Nom de l'équipe extérieure
            - score1 (int): Score domicile
            - score2 (int): Score extérieur
            - statut (str): Statut du match
        Liste vide si aucun match en cours.
    """
    client = ctx.app_context.client
    lives = await _safe_call(ctx, "Récupération des matchs en direct", client.get_lives_async())
    if not lives:
        return []
    return [serialize_model(live) for live in lives]


# ---------------------------------------------------------------------------
# Outils MCP — Saisons
# ---------------------------------------------------------------------------

@mcp.tool(
    name="ffbb_get_saisons",
    annotations=_READONLY_ANNOTATIONS,
    description=(
        "Récupère la liste des saisons de basketball. "
        "Paramètre `active_only` pour ne retourner que les saisons actives. "
        "Retourne les IDs et noms des saisons, utiles pour filtrer les compétitions."
    ),
)
async def ffbb_get_saisons(params: SaisonsInput, ctx: Ctx) -> list[dict[str, Any]]:
    """Liste des saisons (filtre actif possible).

    Args:
        params (SaisonsInput): Paramètres validés contenant :
            - active_only (bool): Si True, filtre les saisons actives uniquement

    Returns:
        list[dict]: Liste de saisons. Chaque dict contient :
            - id (int): ID de la saison
            - nom (str): Nom de la saison (ex: "2024-2025")
            - actif (bool): Si la saison est active
    """
    client = ctx.app_context.client
    label = "saisons actives" if params.active_only else "toutes les saisons"
    saisons = await _safe_call(
        ctx,
        f"Récupération des {label}",
        client.get_saisons_async(active_only=params.active_only),
    )
    if not saisons:
        return []
    return [serialize_model(s) for s in saisons]


# ---------------------------------------------------------------------------
# Outils MCP — Détails par ID
# ---------------------------------------------------------------------------

@mcp.tool(
    name="ffbb_get_competition",
    annotations=_READONLY_ANNOTATIONS,
    description=(
        "Récupère les détails complets d'une compétition FFBB par son ID. "
        "Retourne le nom, le type, la saison, les poules et les équipes. "
        "Utilise ffbb_search_competitions pour trouver l'ID."
    ),
)
async def ffbb_get_competition(params: CompetitionIdInput, ctx: Ctx) -> dict[str, Any]:
    """Détails d'une compétition par ID.

    Args:
        params (CompetitionIdInput): Paramètres validés contenant :
            - competition_id (int): ID de la compétition

    Returns:
        dict: Détails de la compétition incluant nom, type, saison, poules, équipes.
        Dict vide si l'ID est introuvable.
    """
    client = ctx.app_context.client
    comp = await _safe_call(
        ctx,
        f"Récupération compétition #{params.competition_id}",
        client.get_competition_async(competition_id=params.competition_id),
    )
    return serialize_model(comp) or {}


@mcp.tool(
    name="ffbb_get_poule",
    annotations=_READONLY_ANNOTATIONS,
    description=(
        "Récupère les détails d'une poule/groupe d'une compétition. "
        "Retourne le classement, les équipes, les matchs joués et à venir. "
        "L'ID de poule est disponible via ffbb_get_competition."
    ),
)
async def ffbb_get_poule(params: PouleIdInput, ctx: Ctx) -> dict[str, Any]:
    """Détails d'une poule/groupe par ID (classement, matchs).

    Args:
        params (PouleIdInput): Paramètres validés contenant :
            - poule_id (int): ID de la poule

    Returns:
        dict: Détails de la poule incluant classement, équipes, matchs.
        Dict vide si l'ID est introuvable.
    """
    client = ctx.app_context.client
    poule = await _safe_call(
        ctx,
        f"Récupération poule #{params.poule_id}",
        client.get_poule_async(poule_id=params.poule_id),
    )
    return serialize_model(poule) or {}


@mcp.tool(
    name="ffbb_get_organisme",
    annotations=_READONLY_ANNOTATIONS,
    description=(
        "Récupère les informations détaillées d'un club ou organisme FFBB par son ID. "
        "Retourne le nom, l'adresse, le type et les équipes engagées. "
        "Utilise ffbb_search_organismes pour trouver l'ID."
    ),
)
async def ffbb_get_organisme(params: OrganismeIdInput, ctx: Ctx) -> dict[str, Any]:
    """Informations détaillées d'un club/organisme (adresse, équipes...).

    Args:
        params (OrganismeIdInput): Paramètres validés contenant :
            - organisme_id (int): ID de l'organisme

    Returns:
        dict: Détails de l'organisme incluant nom, adresse, type, équipes.
        Dict vide si l'ID est introuvable.
    """
    client = ctx.app_context.client
    org = await _safe_call(
        ctx,
        f"Récupération organisme #{params.organisme_id}",
        client.get_organisme_async(organisme_id=params.organisme_id),
    )
    return serialize_model(org) or {}


@mcp.tool(
    name="ffbb_equipes_club",
    annotations=_READONLY_ANNOTATIONS,
    description=(
        "Récupère uniquement la liste des équipes engagées par un club/organisme. "
        "Plus léger que ffbb_get_organisme car ne retourne que les engagements. "
        "Utilise ffbb_search_organismes pour trouver l'ID du club d'abord."
    ),
)
async def ffbb_equipes_club(params: OrganismeIdInput, ctx: Ctx) -> list[dict[str, Any]]:
    """Liste allégée des équipes engagées par un club.

    Args:
        params (OrganismeIdInput): Paramètres validés contenant :
            - organisme_id (int): ID de l'organisme

    Returns:
        list[dict]: Liste des équipes engagées avec compétition, catégorie, poule.
        Liste vide si aucune équipe.
    """
    client = ctx.app_context.client
    org = await _safe_call(
        ctx,
        f"Récupération des équipes du club #{params.organisme_id}",
        client.get_organisme_async(organisme_id=params.organisme_id),
    )
    if not org:
        return []
    data = serialize_model(org)
    engagements = data.get("engagements", []) if isinstance(data, dict) else []
    await ctx.info(f"✅ {len(engagements)} équipe(s) trouvée(s)")
    return engagements


@mcp.tool(
    name="ffbb_get_classement",
    annotations=_READONLY_ANNOTATIONS,
    description=(
        "Récupère uniquement le classement d'une poule/groupe (sans les matchs). "
        "Plus léger que ffbb_get_poule pour obtenir les positions des équipes. "
        "L'ID de poule est disponible via ffbb_get_competition."
    ),
)
async def ffbb_get_classement(params: PouleIdInput, ctx: Ctx) -> list[dict[str, Any]]:
    """Classement seul d'une poule (sans les rencontres).

    Args:
        params (PouleIdInput): Paramètres validés contenant :
            - poule_id (int): ID de la poule

    Returns:
        list[dict]: Classement trié. Chaque dict contient :
            - position, equipe, points, victoires, defaites, etc.
        Liste vide si non disponible.
    """
    client = ctx.app_context.client
    poule = await _safe_call(
        ctx,
        f"Récupération classement poule #{params.poule_id}",
        client.get_poule_async(poule_id=params.poule_id),
    )
    if not poule:
        return []
    data = serialize_model(poule)
    classement = data.get("classement", []) if isinstance(data, dict) else []
    await ctx.info(f"✅ {len(classement)} équipe(s) au classement")
    return classement


@mcp.tool(
    name="ffbb_calendrier_club",
    annotations=_READONLY_ANNOTATIONS,
    description=(
        "Recherche les matchs à venir et passés d'un club, avec filtre optionnel "
        "par catégorie. Combine le nom du club et la catégorie pour la recherche. "
        "Exemples : club='ASVEL' catégorie='U13M', club='Vichy' catégorie='Seniors'."
    ),
)
async def ffbb_calendrier_club(
    params: CalendrierClubInput, ctx: Ctx
) -> list[dict[str, Any]]:
    """Calendrier des matchs d'un club (filtrage optionnel par catégorie).

    Args:
        params (CalendrierClubInput): Paramètres validés contenant :
            - club_name (str): Nom du club
            - categorie (str): Catégorie optionnelle (ex: 'U11M')

    Returns:
        list[dict]: Liste de matchs avec dates, équipes, résultats.
        Liste vide si aucun match trouvé.
    """
    client = ctx.app_context.client
    query = params.club_name
    if params.categorie:
        query += f" {params.categorie}"

    results = await _safe_call(
        ctx,
        f"Recherche calendrier: « {query} »",
        client.search_rencontres_async(query),
    )
    if not results or not results.hits:
        await ctx.info(f"Aucun match trouvé pour « {query} »")
        return []
    await ctx.info(f"✅ {len(results.hits)} match(s) trouvé(s)")
    return [serialize_model(hit) for hit in results.hits]


# ---------------------------------------------------------------------------
# Outils MCP — Recherche par type (factory pattern)
# ---------------------------------------------------------------------------

_SEARCH_TOOLS: list[tuple[str, str, str]] = [
    (
        "competitions",
        "search_competitions_async",
        "Recherche des compétitions FFBB par nom (championnat, coupe, etc.). "
        "Retourne une liste de compétitions avec leurs IDs et informations de base. "
        "Exemples : 'Championnat', 'Nationale', 'Pro B', 'Coupe de France'.",
    ),
    (
        "organismes",
        "search_organismes_async",
        "Recherche des clubs, associations ou organismes FFBB par nom ou ville. "
        "Retourne une liste d'organismes avec leurs IDs, noms et localisations. "
        "Exemples : 'Paris', 'Lyon', 'Basket Club', 'ASVEL'.",
    ),
    (
        "rencontres",
        "search_rencontres_async",
        "Recherche des rencontres (matchs) FFBB par nom d'équipe ou de compétition. "
        "Retourne les matchs correspondants avec dates, équipes et résultats. "
        "Exemples : 'ASVEL', 'Metropolitans', 'Nationale 1'.",
    ),
    (
        "salles",
        "search_salles_async",
        "Recherche des salles de basketball FFBB par nom ou ville. "
        "Retourne les salles avec leur adresse complète et localisation. "
        "Exemples : 'Paris', 'Bercy', 'Astroballe'.",
    ),
    (
        "pratiques",
        "search_pratiques_async",
        "Recherche des pratiques de basketball (3x3, 5x5, VxE, etc.).",
    ),
    (
        "terrains",
        "search_terrains_async",
        "Recherche des terrains de basketball par nom ou ville.",
    ),
    (
        "tournois",
        "search_tournois_async",
        "Recherche des tournois de basketball.",
    ),
]


def _register_search_tools() -> None:
    """Enregistre les 7 outils de recherche via un factory pattern."""
    for search_type, method_name, description in _SEARCH_TOOLS:
        _create_search_tool(search_type, method_name, description)


def _create_search_tool(search_type: str, method_name: str, description: str) -> None:
    """Crée et enregistre un outil de recherche MCP."""
    st = search_type
    mn = method_name

    @mcp.tool(
        name=f"ffbb_search_{st}",
        annotations=_READONLY_ANNOTATIONS,
        description=description,
    )
    async def search_fn(params: SearchInput, ctx: Ctx) -> list[dict[str, Any]]:
        f"""Recherche de {st} par nom.

        Args:
            params (SearchInput): Paramètres validés contenant :
                - name (str): Terme de recherche (1-200 caractères)

        Returns:
            list[dict]: Liste de résultats. Chaque dict contient un ID et des infos de base.
            Liste vide si aucun résultat.
        """
        client = ctx.app_context.client
        method = getattr(client, mn)
        results = await _safe_call(
            ctx,
            f"Recherche {st}: « {params.name} »",
            method(params.name),
        )
        if not results or not results.hits:
            await ctx.info(f"Aucun résultat pour {st}: « {params.name} »")
            return []
        await ctx.info(f"✅ {len(results.hits)} résultat(s) trouvé(s)")
        return [serialize_model(hit) for hit in results.hits]


# Register all search tools
_register_search_tools()


# ---------------------------------------------------------------------------
# Outils MCP — Recherche globale multi-types
# ---------------------------------------------------------------------------

@mcp.tool(
    name="ffbb_multi_search",
    annotations=_READONLY_ANNOTATIONS,
    description=(
        "Recherche globale sur tous les types FFBB en une seule requête : "
        "compétitions, clubs, matchs, salles, tournois, terrains. "
        "Idéal pour une première exploration. "
        "Exemples : 'Lyon', 'Pro A', 'Palais des Sports'."
    ),
)
async def ffbb_multi_search(params: SearchInput, ctx: Ctx) -> list[dict[str, Any]]:
    """Recherche globale sur tous les types FFBB.

    Args:
        params (SearchInput): Paramètres validés contenant :
            - name (str): Terme de recherche (1-200 caractères)

    Returns:
        list[dict]: Liste de résultats multi-types. Chaque dict contient :
            - _category (str): Type du résultat (compétitions, organismes, rencontres, salles...)
            - id (str): ID du résultat
            - Plus les champs spécifiques à chaque catégorie.
        Liste vide si aucun résultat.
    """
    client = ctx.app_context.client
    queries = generate_queries(params.name)
    results = await _safe_call(
        ctx,
        f"Recherche multi-types: « {params.name} »",
        client.multi_search_async(queries=queries),
    )
    if not results or not results.results:
        await ctx.info(f"Aucun résultat multi-search pour « {params.name} »")
        return []

    output: list[dict[str, Any]] = []
    for res in results.results:
        if res.hits:
            category = res.index_uid
            for hit in res.hits:
                item = serialize_model(hit)
                item["_category"] = category
                output.append(item)

    await ctx.info(f"✅ {len(output)} résultat(s) trouvé(s) au total")
    return output


# ---------------------------------------------------------------------------
# Resources — données référentielles stables (URI-addressable)
# ---------------------------------------------------------------------------

@mcp.resource("ffbb://saisons")
async def resource_saisons() -> str:
    """Liste des saisons FFBB au format JSON."""
    client = get_client()
    saisons = await client.get_saisons_async()
    return json.dumps(
        [serialize_model(s) for s in saisons] if saisons else [],
        default=str,
    )


@mcp.resource("ffbb://competition/{competition_id}")
async def resource_competition(competition_id: int) -> str:
    """Détails d'une compétition au format JSON."""
    client = get_client()
    comp = await client.get_competition_async(competition_id)
    return json.dumps(serialize_model(comp) or {}, default=str)


@mcp.resource("ffbb://poule/{poule_id}")
async def resource_poule(poule_id: int) -> str:
    """Détails d'une poule au format JSON."""
    client = get_client()
    poule = await client.get_poule_async(poule_id)
    return json.dumps(serialize_model(poule) or {}, default=str)


@mcp.resource("ffbb://organisme/{organisme_id}")
async def resource_organisme(organisme_id: int) -> str:
    """Détails d'un organisme/club au format JSON."""
    client = get_client()
    org = await client.get_organisme_async(organisme_id)
    return json.dumps(serialize_model(org) or {}, default=str)


# ---------------------------------------------------------------------------
# Prompts — templates réutilisables pour workflows courants
# ---------------------------------------------------------------------------

@mcp.prompt()
def analyser_match(match_id: str) -> str:
    """Génère un prompt pour analyser un match spécifique."""
    return (
        f"Analyse le match avec l'ID {match_id}.\n"
        "Utilise l'outil `ffbb_search_rencontres` ou les ressources disponibles "
        "pour trouver les détails.\n"
        "Donne le contexte, les enjeux si possible, et le résultat probable ou affiché."
    )


@mcp.prompt()
def trouver_club(club_name: str, department: str = "") -> str:
    """Aide à trouver un club et ses informations."""
    prompt = f"Je cherche des informations sur le club '{club_name}'"
    if department:
        prompt += f" dans le département ou la ville '{department}'"
    return (
        f"{prompt}.\n"
        "1. Utilise `ffbb_search_organismes` pour trouver l'ID du club\n"
        "2. Puis `ffbb_get_organisme` pour les détails complets\n"
        "3. Liste son adresse et ses équipes engagées cette saison."
    )


@mcp.prompt()
def prochain_match(club_name: str, categorie: str = "") -> str:
    """Aide à trouver le prochain match d'un club."""
    query = club_name
    if categorie:
        query += f" {categorie}"
    return (
        f"Je cherche le prochain match de '{query}'.\n"
        f"1. Utilise `ffbb_calendrier_club` avec club_name='{club_name}'"
        + (f" et categorie='{categorie}'" if categorie else "") + "\n"
        "2. Filtre les résultats pour ne garder que les matchs à venir\n"
        "3. Donne la date, l'heure, l'adversaire et le lieu du prochain match."
    )


@mcp.prompt()
def classement_poule(competition_name: str) -> str:
    """Aide à consulter le classement d'une compétition."""
    return (
        f"Je veux le classement de la compétition '{competition_name}'.\n"
        f"1. Utilise `ffbb_search_competitions` avec « {competition_name} »\n"
        "2. Puis `ffbb_get_competition` pour obtenir les poules\n"
        "3. Puis `ffbb_get_classement` pour le classement de la poule souhaitée\n"
        "4. Présente le classement sous forme de tableau."
    )


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main():
    """Lance le serveur MCP FFBB en mode stdio."""
    logger.info("Démarrage du serveur MCP FFBB...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
