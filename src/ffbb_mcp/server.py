"""
FFBB MCP Server — Serveur MCP pour les données de la Fédération Française de Basketball.

Expose des outils MCP pour accéder aux données FFBB :
- Matchs en direct
- Compétitions, poules, saisons
- Clubs/organismes, salles
- Recherche multi-types
"""

import logging
import os
import traceback
from typing import Any

from ffbb_api_client_v2 import FFBBAPIClientV2, TokenManager
from ffbb_api_client_v2.utils.cache_manager import CacheConfig, CacheManager
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ffbb-mcp")

# ---------------------------------------------------------------------------
# Models (Pydantic)
# ---------------------------------------------------------------------------


class Competition(BaseModel):
    id: int
    libelle: str
    type: str
    saison: str
    organisateur: str | None = None


class Organisme(BaseModel):
    id: int
    libelle: str
    type: str
    adresse: str | None = None
    code_postal: str | None = None
    ville: str | None = None


class Rencontre(BaseModel):
    id: int
    competition: str
    equipe_domicile: str
    equipe_exterieur: str
    score_domicile: int | None = None
    score_exterieur: int | None = None
    statut: str
    date: str


class Salle(BaseModel):
    id: int
    libelle: str
    adresse: str
    ville: str
    capacite: int | None = None


class MultiSearchResult(BaseModel):
    id: int
    libelle: str
    type: str  # Competition, Organisme, Rencontre, etc.
    details: dict[str, Any]


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
# Client FFBB — initialisé à la demande (lazy)
# ---------------------------------------------------------------------------
_client: FFBBAPIClientV2 | None = None


def get_client() -> FFBBAPIClientV2:
    """Retourne le client FFBB, en le créant si nécessaire."""
    global _client
    if _client is None:
        try:
            logger.info("Initialisation du client FFBB...")
            cwd = os.getcwd()
            logger.info(f"CWD: {cwd}")

            # Tentative de suppression du fichier cache
            db_path = os.path.join(cwd, "http_cache.db")
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                    logger.info(f"Supprimé {db_path}")
                except Exception as e:
                    logger.error(f"Impossible de supprimer {db_path}: {e}")

            # Force reset du singleton pour être sûr d'appliquer notre config
            CacheManager.reset_instance()

            # Configuration explicite en mémoire (desactivé pour debug)
            cache_config = CacheConfig(
                backend="memory", enabled=False, expire_after=3600
            )
            cache_manager = CacheManager(config=cache_config)

            # On force use_cache=False pour le token manager
            tokens = TokenManager.get_tokens(use_cache=False)

            _client = FFBBAPIClientV2.create(
                api_bearer_token=tokens.api_token,
                meilisearch_bearer_token=tokens.meilisearch_token,
                cached_session=cache_manager.session,
            )
            logger.info("Client FFBB initialisé avec succès (Cache: Memory).")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation du client: {e}")
            logger.error(traceback.format_exc())
            raise e
    return _client


# ---------------------------------------------------------------------------
# Utilitaire de sérialisation
# ---------------------------------------------------------------------------


def _serialize(obj: Any) -> Any:
    """Convertit un objet FFBB en dict JSON-serializable de manière récursive."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(item) for item in obj]
    if hasattr(obj, "__dict__"):
        return {
            k: _serialize(v)
            for k, v in obj.__dict__.items()
            if not k.startswith("_")
        }
    return str(obj)


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
    return [_serialize(live) for live in lives]


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
    return [_serialize(s) for s in saisons]


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
    return _serialize(competition) or {}


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
    return _serialize(poule) or {}


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
    return _serialize(organisme) or {}


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
    return [_serialize(hit) for hit in results.hits]


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
    return [_serialize(hit) for hit in results.hits]


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
    return [_serialize(hit) for hit in results.hits]


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
    return [_serialize(hit) for hit in results.hits]


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
                item = _serialize(hit)
                item["_category"] = category
                output.append(item)
    return output


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def main():
    """Lance le serveur MCP FFBB en mode stdio."""
    logger.info("Démarrage du serveur MCP FFBB...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
