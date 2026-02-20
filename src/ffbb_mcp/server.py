"""
FFBB MCP Server — Serveur MCP pour les données de la Fédération Française de Basketball.

Expose des outils MCP pour accéder aux données FFBB :
- Matchs en direct
- Compétitions, poules, saisons
- Clubs/organismes, salles
- Recherche multi-types
"""

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from ffbb_mcp.client import get_client
from ffbb_mcp.utils import serialize_model

# ---------------------------------------------------------------------------
# Logging initialization
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ffbb-mcp")

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="ffbb",
    instructions=(
        "Ce serveur expose les données de la Fédération Française de Basketball "
        "(FFBB). "
        "Tu peux consulter les matchs en direct, le calendrier des rencontres, "
        "les résultats, les compétitions, les clubs et les salles de sport. "
        "Commence par une recherche (search_*) pour trouver les IDs, "
        "puis utilise get_* pour les détails."
    ),
)


# ---------------------------------------------------------------------------
# Outils MCP
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Récupère les matchs de basketball en cours (live). "
        "Retourne la liste des rencontres avec les scores actuels, "
        "les équipes et le statut du match. "
        "Utilise cet outil pour suivre les matchs en temps réel."
    )
)
def ffbb_get_lives() -> list[dict[str, Any]]:
    """Matchs en cours (scores live)."""
    client = get_client()
    lives = client.get_lives()
    if not lives:
        return []
    return [serialize_model(live) for live in lives]


@mcp.tool(
    description=(
        "Récupère la liste des saisons de basketball. "
        "Paramètre optionnel `active_only` (bool) pour ne retourner que les "
        "saisons actives. "
        "Retourne les IDs et noms des saisons, utiles pour filtrer les compétitions."
    )
)
def ffbb_get_saisons(active_only: bool = False) -> list[dict[str, Any]]:
    """Liste des saisons (filtre actif possible)."""
    client = get_client()
    filter_criteria = '{"actif":{"_eq":true}}' if active_only else None
    saisons = (
        client.get_saisons(filter_criteria=filter_criteria)
        if filter_criteria
        else client.get_saisons()
    )
    if not saisons:
        return []
    return [serialize_model(s) for s in saisons]


@mcp.tool(
    description=(
        "Récupère les détails complets d'une compétition FFBB à partir de son ID. "
        "Retourne le nom, le type (championnat, coupe...), la saison, "
        "les poules et les équipes engagées. "
        "Utilise ffbb_search_competitions pour trouver l'ID d'une compétition."
    )
)
def ffbb_get_competition(competition_id: int) -> dict[str, Any]:
    """Détails d'une compétition par ID."""
    client = get_client()
    competition = client.get_competition(competition_id=competition_id)
    return serialize_model(competition) or {}


@mcp.tool(
    description=(
        "Récupère les détails d'une poule/groupe au sein d'une compétition. "
        "Retourne le classement, les équipes, les matchs joués et à venir "
        "dans cette poule. "
        "L'ID de poule est disponible dans les détails d'une compétition "
        "(ffbb_get_competition)."
    )
)
def ffbb_get_poule(poule_id: int) -> dict[str, Any]:
    """Détails d'une poule/groupe par ID (classement, matchs)."""
    client = get_client()
    poule = client.get_poule(poule_id=poule_id)
    return serialize_model(poule) or {}


@mcp.tool(
    description=(
        "Récupère les informations détaillées d'un club ou organisme FFBB par son ID. "
        "Retourne le nom, l'adresse, le type d'organisme et les équipes engagées "
        "en compétition. "
        "Utilise ffbb_search_organismes pour trouver l'ID d'un club."
    )
)
def ffbb_get_organisme(organisme_id: int) -> dict[str, Any]:
    """Informations détaillées d'un club/organisme (adresse, équipes...)."""
    client = get_client()
    organisme = client.get_organisme(organisme_id=organisme_id)
    return serialize_model(organisme) or {}


@mcp.tool(
    description=(
        "Recherche des compétitions FFBB par nom (championnat, coupe, etc.). "
        "Retourne une liste de compétitions avec leurs IDs et informations de base. "
        "Exemples : 'Championnat', 'Nationale', 'Pro B', 'Coupe de France'."
    )
)
def ffbb_search_competitions(name: str) -> list[dict[str, Any]]:
    """Recherche de compétitions par nom."""
    client = get_client()
    results = client.search_competitions(name)
    if not results or not results.hits:
        return []
    return [serialize_model(hit) for hit in results.hits]


@mcp.tool(
    description=(
        "Recherche des clubs, associations ou organismes FFBB par nom ou ville. "
        "Retourne une liste d'organismes avec leurs IDs, noms et localisations. "
        "Exemples : 'Paris', 'Lyon', 'Basket Club', 'ASVEL'."
    )
)
def ffbb_search_organismes(name: str) -> list[dict[str, Any]]:
    """Recherche de clubs/associations par nom ou ville."""
    client = get_client()
    results = client.search_organismes(name)
    if not results or not results.hits:
        return []
    return [serialize_model(hit) for hit in results.hits]


@mcp.tool(
    description=(
        "Recherche des rencontres (matchs) FFBB par nom d'équipe ou de compétition. "
        "Retourne les matchs correspondants avec dates, équipes et résultats "
        "si disponibles. "
        "Exemples : 'ASVEL', 'Metropolitans', 'Nationale 1'."
    )
)
def ffbb_search_rencontres(name: str) -> list[dict[str, Any]]:
    """Recherche de matchs/rencontres par nom d'équipe ou compétition."""
    client = get_client()
    results = client.search_rencontres(name)
    if not results or not results.hits:
        return []
    return [serialize_model(hit) for hit in results.hits]


@mcp.tool(
    description=(
        "Recherche des salles de basketball FFBB par nom ou ville. "
        "Retourne les salles avec leur adresse complète et localisation. "
        "Utile pour connaître le lieu d'un match. Exemples : 'Paris', 'Bercy', "
        "'Astroballe'."
    )
)
def ffbb_search_salles(name: str) -> list[dict[str, Any]]:
    """Recherche de salles de sport par nom ou ville."""
    client = get_client()
    results = client.search_salles(name)
    if not results or not results.hits:
        return []
    return [serialize_model(hit) for hit in results.hits]


@mcp.tool(description=("Recherche des pratiques (3x3, 5x5, VxE, etc.)."))
def ffbb_search_pratiques(name: str) -> list[dict[str, Any]]:
    """Recherche de pratiques."""
    client = get_client()
    results = client.search_pratiques(name)
    if not results or not results.hits:
        return []
    return [serialize_model(hit) for hit in results.hits]


@mcp.tool(description=("Recherche des terrains."))
def ffbb_search_terrains(name: str) -> list[dict[str, Any]]:
    """Recherche de terrains."""
    client = get_client()
    results = client.search_terrains(name)
    if not results or not results.hits:
        return []
    return [serialize_model(hit) for hit in results.hits]


@mcp.tool(description=("Recherche des tournois."))
def ffbb_search_tournois(name: str) -> list[dict[str, Any]]:
    """Recherche de tournois."""
    client = get_client()
    results = client.search_tournois(name)
    if not results or not results.hits:
        return []
    return [serialize_model(hit) for hit in results.hits]


@mcp.tool(
    description=(
        "Effectue une recherche globale sur tous les types de données FFBB en une "
        "seule requête : "
        "compétitions, clubs, matchs, salles, tournois, terrains. "
        "Idéal pour une première exploration ou quand on ne sait pas dans quelle "
        "catégorie chercher. "
        "Exemples : 'Lyon', 'Pro A', 'Palais des Sports'."
    )
)
def ffbb_multi_search(name: str) -> list[dict[str, Any]]:
    """Recherche globale sur tous les types (compétitions, clubs, matchs, salles...)."""
    client = get_client()
    results = client.multi_search(name)
    if not results:
        return []
    output = []
    for result in results:
        if hasattr(result, "hits") and result.hits:
            category = type(result).__name__
            for hit in result.hits:
                item = serialize_model(hit)
                item["_category"] = category
                output.append(item)
    return output


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("ffbb://lives")
def resource_lives() -> str:
    """Retourne les matchs en direct au format JSON."""
    client = get_client()
    lives = client.get_lives()
    return json.dumps([serialize_model(live) for live in lives], default=str)


@mcp.resource("ffbb://saisons")
def resource_saisons() -> str:
    """Retourne la liste des saisons au format JSON."""
    client = get_client()
    saisons = client.get_saisons()
    return json.dumps([serialize_model(s) for s in saisons], default=str)


@mcp.resource("ffbb://competition/{competition_id}")
def resource_competition(competition_id: int) -> str:
    """Retourne les détails d'une compétition au format JSON."""
    client = get_client()
    comp = client.get_competition(competition_id)
    return json.dumps(serialize_model(comp), default=str)


@mcp.resource("ffbb://poule/{poule_id}")
def resource_poule(poule_id: int) -> str:
    """Retourne les détails d'une poule au format JSON."""
    client = get_client()
    poule = client.get_poule(poule_id)
    return json.dumps(serialize_model(poule), default=str)


@mcp.resource("ffbb://organisme/{organisme_id}")
def resource_organisme(organisme_id: int) -> str:
    """Retourne les détails d'un organisme au format JSON."""
    client = get_client()
    org = client.get_organisme(organisme_id)
    return json.dumps(serialize_model(org), default=str)


# ---------------------------------------------------------------------------
# Prompts
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
        "Trouve l'ID du club, son adresse, et liste ses équipes engagées cette saison."
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
