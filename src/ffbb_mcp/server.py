import logging
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from .metrics import generate_prometheus_metrics
from .prompts import register_prompts
from .resources import register_resources
from .services import (
    ffbb_bilan_service,
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

_DEFAULT_PUBLIC_URL = "https://ffbb.desimone.fr"
_REMOTE_LOGO_URL = (
    "https://raw.githubusercontent.com/nickdesi/FFBB-MCP-Server/main/assets/logo.webp"
)
_LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "logo.webp"

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
        "Données FFBB (basketball français). "
        "⚡ OUTIL PRIORITAIRE pour tout bilan/résultats/classement : ffbb_bilan(club_name=..., categorie=...) "
        "→ 1 seul appel, retourne tout (toutes phases agrégées). "
        "⚠️ Les données FFBB sont TOUJOURS live — ne jamais chercher en mémoire/cache avant d'appeler l'API. "
        "Autres outils : ffbb_search → trouver un club/compétition. "
        "ffbb_get(type='poule') → classement + matchs d'une poule précise. "
        "ffbb_club(action='calendrier') → dernier recours si aucun poule_id disponible. "
        "Règles : catégorie sans genre → demander M ou F. Plusieurs équipes même catégorie → demander laquelle."
    ),
    dependencies=["mcp", "ffbb-api-client-v3"],
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=_dns_protection,
        allowed_hosts=_allowed_hosts,
        allowed_origins=_allowed_origins,
    ),
)


# ---------------------------------------------------------------------------
# Routes HTTP
# ---------------------------------------------------------------------------


def _get_public_base_url() -> str:
    public_url = os.environ.get("PUBLIC_URL", _DEFAULT_PUBLIC_URL).strip()
    if not public_url:
        return _DEFAULT_PUBLIC_URL
    normalized = public_url.rstrip("/")
    if normalized.endswith("/mcp"):
        normalized = normalized[: -len("/mcp")]
    return normalized or _DEFAULT_PUBLIC_URL


def _get_logo_url() -> str:
    return f"{_get_public_base_url()}/logo.webp"


def _build_index_html() -> str:
    canonical_url = f"{_get_public_base_url()}/"
    logo_url = _get_logo_url()
    # Titre et description orientés MCP, couvrant toutes les fonctionnalités (bilan, recherches, lives, etc.)
    title = (
        "FFBB MCP Server – Serveur MCP pour les données FFBB "
        "(bilans, recherches clubs/salles, calendriers, résultats, classements, lives)"
    )
    description = (
        "FFBB MCP Server est un serveur MCP pour accéder aux données FFBB : recherche de clubs, "
        "compétitions, salles et terrains, bilans d’équipes, calendriers, résultats, classements "
        "et scores live. Connectez vos agents IA au basket français."
    )

    return f"""<!DOCTYPE html>
    <html lang=\"fr\" class=\"bg-gray-900 text-white\">
    <head>
        <meta charset=\"UTF-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
        <title>{title}</title>
        <meta name=\"description\" content=\"{description}\">
        <meta name=\"robots\" content=\"index, follow\">
        <meta name=\"theme-color\" content=\"#111827\">
        <meta name=\"application-name\" content=\"FFBB MCP Server\">
        <link rel=\"canonical\" href=\"{canonical_url}\">
        <!-- Favicon basé sur le logo -->
        <link rel=\"icon\" type=\"image/webp\" href=\"{logo_url}\">
        <link rel=\"apple-touch-icon\" href=\"{logo_url}\">
        <!-- Open Graph / Twitter -->
        <meta property=\"og:locale\" content=\"fr_FR\">
        <meta property=\"og:type\" content=\"website\">
        <meta property=\"og:site_name\" content=\"FFBB MCP Server\">
        <meta property=\"og:title\" content=\"{title}\">
        <meta property=\"og:description\" content=\"{description}\">
        <meta property=\"og:url\" content=\"{canonical_url}\">
        <meta property=\"og:image\" content=\"{logo_url}\">
        <meta name=\"twitter:card\" content=\"summary\">
        <meta name=\"twitter:title\" content=\"{title}\">
        <meta name=\"twitter:description\" content=\"{description}\">
        <meta name=\"twitter:image\" content=\"{logo_url}\">
        <!-- Données structurées SoftwareApplication -->
        <script type=\"application/ld+json\">{{
            \"@context\": \"https://schema.org\",
            \"@type\": \"SoftwareApplication\",
            \"name\": \"FFBB MCP Server\",
            \"applicationCategory\": \"DeveloperApplication\",
            \"operatingSystem\": \"macOS, Windows, Linux\",
            \"description\": \"{description}\",
            \"url\": \"{canonical_url}\",
            \"image\": \"{logo_url}\",
            \"sameAs\": [
                \"https://github.com/nickdesi/FFBB-MCP-Server\",
                \"https://smithery.ai/servers/nickdesi/mcpffbb\"
            ]
        }}</script>
        <script src=\"https://cdn.tailwindcss.com\"></script>
    </head>
    <body class=\"flex flex-col items-center justify-center min-h-screen p-4 text-center\">
        <img src=\"{logo_url}\" alt=\"FFBB MCP Server logo\" class=\"max-w-xs mb-8 rounded-xl shadow-2xl hover:scale-105 transition-transform duration-300\">
        <h1 class=\"text-4xl md:text-6xl font-extrabold mb-4 bg-gradient-to-r from-orange-400 to-red-500 text-transparent bg-clip-text\">FFBB MCP Server</h1>
        <p class=\"text-xl text-gray-300 max-w-2xl mb-8\">
            FFBB MCP Server est un serveur MCP dédié aux données de la Fédération Française de BasketBall (FFBB).<br/>
            Recherchez clubs, compétitions, salles et terrains, générez des bilans d’équipes,
            explorez calendriers, résultats, classements et scores live du basket français directement depuis vos agents IA.
        </p>
        <div class=\"flex flex-wrap justify-center gap-4\">
            <a href=\"https://github.com/nickdesi/FFBB-MCP-Server\" target=\"_blank\" rel=\"noreferrer\" class=\"px-6 py-3 bg-gray-800 hover:bg-gray-700 rounded-lg text-white font-semibold transition-colors\">GitHub</a>
            <a href=\"https://smithery.ai/servers/nickdesi/mcpffbb\" target=\"_blank\" rel=\"noreferrer\" class=\"px-6 py-3 bg-[#e2693e] hover:bg-[#c95d37] rounded-lg text-white font-semibold transition-colors\">Disponible sur Smithery</a>
        </div>
        <div class=\"mt-12 text-gray-500 text-sm\">Statut : <span class=\"text-green-400\">En ligne</span></div>
    </body>
    </html>"""


def _build_robots_txt() -> str:
    base_url = _get_public_base_url()
    return f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n"


def _build_sitemap_xml() -> str:
    canonical_url = f"{_get_public_base_url()}/"
    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
  <url>
    <loc>{canonical_url}</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""


def _logo_response() -> Response:
    if _LOGO_PATH.exists():
        return FileResponse(_LOGO_PATH, media_type="image/webp")
    return RedirectResponse(_REMOTE_LOGO_URL)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok", "service": "ffbb-mcp"})


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics(request: Request) -> Response:
    return PlainTextResponse(generate_prometheus_metrics())


@mcp.custom_route("/logo.webp", methods=["GET"])
async def logo(request: Request) -> Response:
    return _logo_response()


@mcp.custom_route("/favicon.ico", methods=["GET"])
async def favicon(request: Request) -> Response:
    return _logo_response()


@mcp.custom_route("/robots.txt", methods=["GET"])
async def robots_txt(request: Request) -> Response:
    return PlainTextResponse(_build_robots_txt())


@mcp.custom_route("/sitemap.xml", methods=["GET"])
async def sitemap_xml(request: Request) -> Response:
    return Response(_build_sitemap_xml(), media_type="application/xml")


@mcp.custom_route("/", methods=["GET"])
async def index(request: Request) -> Response:
    return HTMLResponse(content=_build_index_html(), status_code=200)


# ---------------------------------------------------------------------------
# TOOL 1 — Recherche unifiée (remplace 8 tools de search)
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_search", annotations=_READONLY_ANNOTATIONS)
async def ffbb_search(
    query: Annotated[
        str, Field(description="Texte libre (ex: 'Vichy', 'U13F Auvergne').")
    ],
    type: Annotated[
        Literal[
            "all",
            "competitions",
            "organismes",
            "rencontres",
            "salles",
            "pratiques",
            "terrains",
            "tournois",
        ],
        Field(description="Type de données. 'all' cherche partout (défaut)."),
    ] = "all",
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Recherche FFBB — clubs, compétitions, matchs, salles, tournois, etc.

    type='all' → recherche globale (meilleur point d'entrée).
    type='organismes' → clubs uniquement.
    type='competitions' → compétitions uniquement.
    Résultats contiennent un 'id' à utiliser avec ffbb_get ou ffbb_club.
    """
    try:
        if type == "all":
            return await multi_search_service(nom=query, limit=limit)
        dispatch = {
            "competitions": search_competitions_service,
            "organismes": search_organismes_service,
            "salles": search_salles_service,
            "rencontres": search_rencontres_service,
            "pratiques": search_pratiques_service,
            "terrains": search_terrains_service,
            "tournois": search_tournois_service,
        }
        return await dispatch[type](nom=query, limit=limit)
    except Exception as e:
        logger.error(f"ffbb_search failed: {e}")
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# TOOL 2 — Bilan complet toutes phases (1 appel = tout le workflow)
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_bilan", annotations=_READONLY_ANNOTATIONS)
async def ffbb_bilan(
    club_name: Annotated[
        str | None,
        Field(description="Nom du club (ex: 'Stade Clermontois', 'ASVEL')."),
    ] = None,
    organisme_id: Annotated[
        int | str | None,
        Field(description="ID FFBB du club (alternative plus rapide à club_name)."),
    ] = None,
    categorie: Annotated[
        str | None,
        Field(
            description="Catégorie + genre + numéro équipe (ex: 'U11M1', 'U13F2', 'U15M', 'Senior')."
        ),
    ] = None,
) -> dict[str, Any]:
    """Bilan complet d'une équipe toutes phases confondues en UN seul appel.

    ⚡ C'est l'outil à utiliser en priorité pour toute question de type
    "quel est le bilan de X cette saison ?" ou "résultats de U11M1".

    Encapsule en interne : recherche club → équipes → classements de toutes
    les phases en parallèle → agrégation V/D/N et paniers marqués/encaissés.

    Retourne :
    - bilan_total : total V/D/N, paniers marqués/encaissés, différence
    - phases : détail par compétition/phase (position, V/D/N, paniers)
    """
    try:
        return await ffbb_bilan_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
        )
    except Exception as e:
        logger.error(f"ffbb_bilan failed: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# TOOL 3 — Détails par ID (remplace get_competition + get_poule + get_organisme)
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_get", annotations=_READONLY_ANNOTATIONS)
async def ffbb_get(
    id: Annotated[int | str, Field(description="ID numérique de l'entité.")],
    type: Annotated[
        Literal["competition", "poule", "organisme"],
        Field(description="Type : 'competition', 'poule', ou 'organisme' (club)."),
    ],
) -> dict[str, Any]:
    """Détails d'une entité FFBB par son ID.

    type='competition' → infos compétition + liste des poules.
    type='poule' → classement + toutes les rencontres de la poule.
                   ⚡ Si tu as déjà un poule_id, utilise TOUJOURS ce type
                   pour récupérer les matchs — c'est plus rapide que
                   ffbb_club(action='calendrier').
    type='organisme' → infos club + engagements saison.
    L'ID vient des résultats de ffbb_search.
    """
    try:
        if type == "competition":
            return await get_competition_service(competition_id=id)
        elif type == "poule":
            return await get_poule_service(poule_id=id)
        elif type == "organisme":
            return await get_organisme_service(organisme_id=id)
        return {"error": f"Type inconnu: {type}"}
    except Exception as e:
        logger.error(f"ffbb_get failed: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# TOOL 4 — Club unifié (remplace get_equipes_club + get_classement + get_calendrier_club)
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_club", annotations=_READONLY_ANNOTATIONS)
async def ffbb_club(
    action: Annotated[
        Literal["calendrier", "equipes", "classement"],
        Field(
            description="'calendrier' → tous les matchs. 'equipes' → liste des équipes engagées. 'classement' → classement d'une poule."
        ),
    ],
    organisme_id: Annotated[
        int | str | None, Field(description="ID du club (si connu).")
    ] = None,
    club_name: Annotated[
        str | None, Field(description="Nom du club (alternative à organisme_id).")
    ] = None,
    filtre: Annotated[
        str | None,
        Field(description="Filtre catégorie/genre (ex: 'U11', 'U13F', 'Senior')."),
    ] = None,
    poule_id: Annotated[
        int | str | None,
        Field(description="ID de la poule (requis pour action='classement')."),
    ] = None,
) -> list[dict[str, Any]]:
    """Actions sur un club FFBB : calendrier, équipes ou classement.

    action='calendrier' → UNIQUEMENT si tu n'as pas de poule_id.
                          Workflow lourd (recherche → équipes → poules).
                          Nécessite organisme_id ou club_name.
                          ⚠️ Si tu as déjà un poule_id, utilise plutôt
                          ffbb_get(id=poule_id, type='poule') — beaucoup plus rapide.
    action='equipes'    → liste des équipes engagées + leurs poule_id (nécessite organisme_id).
                          Utilise ensuite ffbb_get(type='poule') avec le poule_id obtenu.
    action='classement' → classement simplifié d'une poule (nécessite poule_id).
    """
    try:
        if action == "calendrier":
            if not organisme_id and not club_name:
                return [{"error": "Fournir organisme_id ou club_name"}]
            return await get_calendrier_club_service(
                club_name=club_name, organisme_id=organisme_id, categorie=filtre
            )
        elif action == "equipes":
            if not organisme_id:
                return [{"error": "organisme_id requis pour action='equipes'"}]
            return await ffbb_equipes_club_service(
                organisme_id=organisme_id, filtre=filtre
            )
        elif action == "classement":
            if not poule_id:
                return [{"error": "poule_id requis pour action='classement'"}]
            return await ffbb_get_classement_service(poule_id=poule_id)
        return [{"error": f"Action inconnue: {action}"}]
    except Exception as e:
        logger.error(f"ffbb_club failed: {e}")
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# TOOL 5 — Scores en direct
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_lives", annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_lives() -> list[dict[str, Any]]:
    """Matchs en cours (scores live, cache 30s). Retourne [] si aucun match."""
    try:
        return await get_lives_service()
    except Exception as e:
        logger.error(f"ffbb_lives failed: {e}")
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# TOOL 6 — Saisons
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_saisons", annotations=_READONLY_ANNOTATIONS)
async def ffbb_get_saisons(
    active_only: Annotated[
        bool, Field(description="True = saison active uniquement.")
    ] = False,
) -> list[dict[str, Any]]:
    """Liste des saisons FFBB. active_only=True pour la saison en cours uniquement."""
    try:
        return await get_saisons_service(active_only=active_only)
    except Exception as e:
        logger.error(f"ffbb_saisons failed: {e}")
        return [{"error": str(e)}]


# ---------------------------------------------------------------------------
# Injections
# ---------------------------------------------------------------------------

register_prompts(mcp)
register_resources(mcp)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    mode = os.environ.get("MCP_MODE", "stdio").lower()

    if mode == "sse":
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "9123"))
        logger.info(f"Démarrage MCP FFBB en mode Streamable HTTP sur {host}:{port}...")
        mcp.settings.streamable_http_path = "/mcp"
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        logger.info("Démarrage MCP FFBB en mode stdio...")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
