import logging
import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AliasChoices, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .prompts import register_prompts
from .resources import register_resources
from .services import (
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    get_calendrier_club_service,
    get_competition_service,
    get_lives_service,
    get_organisme_service,
    get_poule_service,
    get_saisons_service,
    multi_search_service,
    search_competitions_service,
    search_organismes_service,
    search_pratiques_service,
    search_rencontres_service,
    search_salles_service,
    search_terrains_service,
    search_tournois_service,
)

logger = logging.getLogger("ffbb-mcp")

# Read-only annotations (all FFBB tools are read-only)
_READONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

# ---------------------------------------------------------------------------
# Initialisation FastMCP
# ---------------------------------------------------------------------------

_allowed_hosts = os.environ.get("ALLOWED_HOSTS", "*").split(",")
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
_dns_protection = os.environ.get("ENABLE_DNS_PROTECTION", "false").lower() == "true"

mcp = FastMCP(
    "FFBB MCP Server",
    instructions=(
        "Ce serveur expose les données de la Fédération Française de Basketball "
        "(FFBB). "
        "Tu peux consulter les matchs en direct, le calendrier des rencontres, "
        "les résultats, les compétitions, les clubs et les salles de sport.\n\n"
        "🚨 REGLES DE DESAMBIGUISATION OBLIGATOIRES :\n"
        "1. Si on te donne une catégorie (ex: 'U11') sans préciser le genre, "
        "demande TOUJOURS si c'est Masculin (M) ou Féminin (F).\n"
        "2. Si un club a plusieurs équipes dans la même catégorie (ex: Équipe 1, Équipe 2), "
        "demande TOUJOURS quelle équipe l'utilisateur veut voir, et repère la bonne poule en fonction "
        "du niveau ou des adversaires.\n"
        "3. Lors d'analyses sur plusieurs phases, croise les équipes adverses pour t'assurer "
        "de suivre exactement la même équipe d'une phase à l'autre (l'Équipe 1 peut perdre son suffixe '- 1' mais reste avec les équipes fortes).\n\n"
        "Workflow recommandé :\n"
        "1. Utilise `ffbb_multi_search` pour une exploration générale\n"
        "2. Ou `ffbb_search_*` pour cibler un type précis "
        "(compétitions, clubs, matchs, salles, pratiques, terrains, tournois)\n"
        "3. Puis `ffbb_get_*` (ou ffbb_calendrier_club) avec l'ID obtenu pour les détails complets\n\n"
        "Tous les outils renvoient du JSON structuré."
    ),
    dependencies=["mcp", "ffbb-api-client-v3"],
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=_dns_protection,
        allowed_hosts=_allowed_hosts,
        allowed_origins=_allowed_origins,
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    """Endpoint de santé pour Coolify."""
    return JSONResponse({"status": "ok", "service": "ffbb-mcp"})


# ---------------------------------------------------------------------------
# Outils MCP — Méta
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_version() -> dict[str, str]:
    """Version et informations du serveur MCP FFBB.

    Retourne la version du serveur, les TTL de cache configurés,
    et l'URL du serveur distant par défaut. Utile pour diagnostiquer
    les problèmes de connexion ou vérifier la compatibilité.

    Returns:
        dict: version, server, remote_url, cache_ttls.
    """
    from . import __version__

    return {
        "version": __version__,
        "server": "FFBB MCP Server",
        "remote_url": os.environ.get("PUBLIC_URL", "https://ffbb.desimone.fr/mcp"),
        "cache_ttls": {
            "lives": "30s",
            "searches": "2min",
            "details": "5min",
        },
    }


# ---------------------------------------------------------------------------
# Outils MCP — Données en direct
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_lives() -> list[dict[str, Any]]:
    """Matchs en cours (scores live).

    Retourne la liste des matchs en direct avec les scores actuels.
    Les données sont mises à jour toutes les 30 secondes (cache 30s).
    Renvoie une liste vide `[]` si aucun match n'est en cours.

    Returns:
        list[dict]: Liste de matchs en direct.
    """
    try:
        return await get_lives_service()
    except Exception as e:
        logger.error(f"ffbb_get_lives failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


# ---------------------------------------------------------------------------
# Outils MCP — Saisons
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_saisons(active_only: bool = False) -> list[dict[str, Any]]:
    """Liste des saisons FFBB (filtre actif possible).

    Retourne la liste des saisons sportives FFBB. Utilise `active_only=True`
    pour ne récupérer que la saison en cours (ex: "2025-2026").

    Args:
        active_only: Si True, ne retourne que la saison active.
    """
    try:
        return await get_saisons_service(active_only=active_only)
    except Exception as e:
        logger.error(f"ffbb_get_saisons failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


# ---------------------------------------------------------------------------
# Outils MCP — Détails par ID
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_competition(
    competition_id: Annotated[
        int | str, Field(validation_alias=AliasChoices("competition_id", "id"))
    ],
) -> dict[str, Any]:
    """Détails d'une compétition par ID.

    Retourne les informations complètes d'une compétition : nom, catégorie,
    sexe, type, et la liste des poules associées.
    L'ID peut être obtenu via `ffbb_search_competitions`.

    Après cet appel, utilise `ffbb_get_poule` avec un poule_id
    pour obtenir le classement et les matchs d'une poule spécifique.

    Args:
        competition_id: ID numérique de la compétition (ex: 200000).
    """
    try:
        return await get_competition_service(competition_id=competition_id)
    except Exception as e:
        logger.error(f"ffbb_get_competition failed: {e}")
        return {"error": "Service FFBB indisponible", "detail": str(e)}


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_poule(
    poule_id: Annotated[
        int | str, Field(validation_alias=AliasChoices("poule_id", "id"))
    ],
) -> dict[str, Any]:
    """Détails d'une poule/groupe par ID (classement, matchs).

    Retourne le classement complet et la liste des rencontres d'une poule.
    L'ID est obtenu depuis les résultats de `ffbb_get_competition` ou
    `ffbb_equipes_club`.

    Pour obtenir uniquement le classement simplifié, préfère `ffbb_get_classement`.

    Args:
        poule_id: ID numérique de la poule (ex: 200000003030720).
    """
    try:
        return await get_poule_service(poule_id=poule_id)
    except Exception as e:
        logger.error(f"ffbb_get_poule failed: {e}")
        return {"error": "Service FFBB indisponible", "detail": str(e)}


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_organisme(
    organisme_id: Annotated[
        int | str, Field(validation_alias=AliasChoices("organisme_id", "id", "club_id"))
    ],
) -> dict[str, Any]:
    """Informations détaillées d'un club/organisme (adresse, équipes...).

    Retourne toutes les informations d'un club : nom, adresse, coordonnées,
    et la liste de ses engagements (équipes inscrites) pour la saison.
    L'ID est obtenu via `ffbb_search_organismes`.

    Pour une vue simplifiée des équipes, utilise plutôt `ffbb_equipes_club`.

    Args:
        organisme_id: ID numérique du club/organisme (ex: 4630).
    """
    try:
        return await get_organisme_service(organisme_id=organisme_id)
    except Exception as e:
        logger.error(f"ffbb_get_organisme failed: {e}")
        return {"error": "Service FFBB indisponible", "detail": str(e)}


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_equipes_club(
    organisme_id: Annotated[
        int | str, Field(validation_alias=AliasChoices("organisme_id", "id", "club_id"))
    ],
    filtre: str | None = None,
) -> list[dict[str, Any]]:
    """Récupère uniquement la liste des équipes engagées par un club/organisme.

    Retourne une liste aplatie avec pour chaque équipe : nom, compétition,
    competition_id, poule_id, catégorie, sexe, et niveau.
    Utilise le `poule_id` retourné pour appeler ensuite `ffbb_get_classement`.

    Args:
        organisme_id: ID du club (obtenu via `ffbb_search_organismes`).
        filtre: Filtre optionnel sur le nom de compétition (ex: "U11", "Senior").
    """
    try:
        return await ffbb_equipes_club_service(organisme_id=organisme_id, filtre=filtre)
    except Exception as e:
        logger.error(f"ffbb_equipes_club failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_classement(
    poule_id: Annotated[
        int | str, Field(validation_alias=AliasChoices("poule_id", "id"))
    ],
) -> list[dict[str, Any]]:
    """Récupère uniquement le classement d'une poule/groupe (sans les matchs).

    Retourne une liste ordonnée avec pour chaque équipe : position, nom,
    points, matchs joués, victoires, défaites, différence.
    Le poule_id est obtenu via `ffbb_equipes_club` ou `ffbb_get_competition`.

    Args:
        poule_id: ID numérique de la poule (ex: 200000003030720).
    """
    try:
        return await ffbb_get_classement_service(poule_id=poule_id)
    except Exception as e:
        logger.error(f"ffbb_get_classement failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


# ---------------------------------------------------------------------------
# Outils MCP — Recherche
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_competitions(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))],
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Recherche des compétitions FFBB par nom.

    Utilise ce tool pour trouver une compétition par son nom
    (ex: "Nationale 1", "U11 Masculin", "Départemental Féminin").
    Retourne une liste d'objets avec id, nom, catégorie, sexe.
    Appelle ensuite `ffbb_get_competition` avec l'id obtenu pour les détails.

    Args:
        nom: Texte de recherche (ex: "Nationale 1", "U13F Auvergne").
        limit: Nombre max de résultats (défaut: 20).
    """
    try:
        return await search_competitions_service(nom=nom, limit=limit)
    except Exception as e:
        logger.error(f"ffbb_search_competitions failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_organismes(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))],
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Recherche des clubs/organismes FFBB par nom.

    Trouve un club par son nom ou sa ville
    (ex: "Vichy", "Stade Clermontois", "Paris Basketball").
    Retourne une liste avec id, nom, adresse.
    Appelle ensuite `ffbb_get_organisme` avec l'id pour les détails complets.

    Args:
        nom: Texte de recherche (nom du club ou de la ville).
        limit: Nombre max de résultats (défaut: 20).
    """
    try:
        return await search_organismes_service(nom=nom, limit=limit)
    except Exception as e:
        logger.error(f"ffbb_search_organismes failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_salles(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))],
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Recherche des salles de basket par nom/ville.

    Trouve une salle de sport par son nom ou sa localisation
    (ex: "Gymnase Desaix", "Clermont-Ferrand", "Palais des Sports").

    Args:
        nom: Texte de recherche (nom de la salle ou ville).
        limit: Nombre max de résultats (défaut: 20).
    """
    try:
        return await search_salles_service(nom=nom, limit=limit)
    except Exception as e:
        logger.error(f"ffbb_search_salles failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_rencontres(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))],
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Recherche des rencontres (matchs) FFBB.

    Recherche des matchs par nom d'équipe ou de compétition
    (ex: "Vichy", "Stade Clermontois U11").
    Retourne les rencontres avec date, équipes, score.
    Pour le calendrier complet d'un club, préfère `ffbb_calendrier_club`.

    Args:
        nom: Texte de recherche (nom d'équipe ou compétition).
        limit: Nombre max de résultats (défaut: 20).
    """
    try:
        return await search_rencontres_service(nom=nom, limit=limit)
    except Exception as e:
        logger.error(f"ffbb_search_rencontres failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_pratiques(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))],
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Recherche des pratiques de basketball.

    Trouve des activités / pratiques proposées par les clubs
    (ex: "3x3", "baby basket", "basket santé", "basket inclusif").

    Args:
        nom: Texte de recherche (type de pratique).
        limit: Nombre max de résultats (défaut: 20).
    """
    try:
        return await search_pratiques_service(nom=nom, limit=limit)
    except Exception as e:
        logger.error(f"ffbb_search_pratiques failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_terrains(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))],
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Recherche des terrains de basketball.

    Trouve des terrains de basket en extérieur (playgrounds)
    par nom ou localisation (ex: "Paris", "Marseille", "Lyon").

    Args:
        nom: Texte de recherche (ville ou nom du terrain).
        limit: Nombre max de résultats (défaut: 20).
    """
    try:
        return await search_terrains_service(nom=nom, limit=limit)
    except Exception as e:
        logger.error(f"ffbb_search_terrains failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_search_tournois(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))],
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Recherche des tournois de basketball.

    Trouve des tournois par nom, catégorie ou lieu
    (ex: "tournoi été", "U13", "3x3 Paris").

    Args:
        nom: Texte de recherche (nom du tournoi, catégorie, ville).
        limit: Nombre max de résultats (défaut: 20).
    """
    try:
        return await search_tournois_service(nom=nom, limit=limit)
    except Exception as e:
        logger.error(f"ffbb_search_tournois failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_multi_search(
    nom: Annotated[str, Field(validation_alias=AliasChoices("nom", "query"))],
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Recherche globale FFBB sur tous les types simultanément.

    Recherche dans : clubs, compétitions, rencontres, salles, pratiques,
    terrains et tournois en un seul appel. Chaque résultat contient un
    champ `_type` indiquant sa catégorie (ex: "organismes", "competitions").

    C'est le meilleur point d'entrée si tu ne sais pas quel type chercher.
    Utilise ensuite `ffbb_get_*` avec l'id du résultat approprié.

    Args:
        nom: Texte de recherche libre (ex: "Vichy", "U11 Auvergne").
        limit: Nombre max de résultats au total (défaut: 20).
    """
    try:
        return await multi_search_service(nom=nom, limit=limit)
    except Exception as e:
        logger.error(f"ffbb_multi_search failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


# ---------------------------------------------------------------------------
# Outils MCP — Aggrégation
# ---------------------------------------------------------------------------


@mcp.tool(annotations=_READONLY_ANNOTATIONS)
async def ffbb_calendrier_club(
    club_name: Annotated[
        str | None, Field(validation_alias=AliasChoices("club_name", "nom"))
    ] = None,
    organisme_id: Annotated[
        int | str | None,
        Field(validation_alias=AliasChoices("organisme_id", "club_id", "id")),
    ] = None,
    categorie: str | None = None,
) -> list[dict[str, Any]]:
    """Récupère le calendrier (prochains matchs) d'un club.

    Fournir soit `club_name` soit `organisme_id` (l'un ou l'autre).
    Si `organisme_id` est fourni, le nom du club est résolu automatiquement.
    Filtre optionnel par catégorie (ex: "U11", "Senior", "U13F").

    Retourne une liste simplifiée : id, date, equipe1, equipe2, num_journee.

    Args:
        club_name: Nom du club (ex: "Stade Clermontois").
        organisme_id: ID du club (alternative au nom).
        categorie: Filtre catégorie optionnel (ex: "U11", "Senior").
    """
    if not club_name and not organisme_id:
        return [{"error": "Paramètre manquant : fournir soit club_name soit organisme_id"}]
    
    try:
        return await get_calendrier_club_service(
            club_name=club_name, organisme_id=organisme_id, categorie=categorie
        )
    except Exception as e:
        logger.error(f"ffbb_calendrier_club failed: {e}")
        return [{"error": "Service FFBB indisponible", "detail": str(e)}]


# ---------------------------------------------------------------------------
# Injections
# ---------------------------------------------------------------------------

register_prompts(mcp)
register_resources(mcp)

# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def main() -> None:
    """Lance le serveur MCP FFBB."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    mode = os.environ.get("MCP_MODE", "stdio").lower()

    if mode == "sse":
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "9123"))

        logger.info(
            f"Démarrage du serveur MCP FFBB en mode Streamable HTTP sur {host}:{port}..."
        )
        # On utilise mcp.run pour gérer tout le cycle de vie du serveur (TaskGroups, sessions, etc.)
        # On définit le chemin vers /mcp pour correspondre à l'attendue.
        mcp.settings.streamable_http_path = "/mcp"
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        logger.info("Démarrage du serveur MCP FFBB en mode stdio...")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
