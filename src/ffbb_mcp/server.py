import asyncio
import logging
import os
import platform
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from . import __version__ as _PACKAGE_VERSION
from .metrics import generate_prometheus_metrics
from .prompts import register_prompts
from .resources import register_resources
from .services import (
    ffbb_bilan_service,
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    ffbb_last_result_service,
    ffbb_next_match_service,
    ffbb_resolve_team_service,
    ffbb_saison_bilan_service,
    get_cache_ttls,
    get_calendrier_club_service,
    get_competition_service,
    get_lives_service,
    get_organisme_service,
    get_poule_service,
    get_saisons_service,
    multi_search_service,
    resolve_poule_id_service,
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
        "Pour le bilan détaillé d'une équipe précise (U11M1, etc.), utiliser ffbb_bilan_saison(organisme_id=..., categorie=..., numero_equipe=...). "
        "Pour le prochain match d'une équipe précise, utiliser ffbb_next_match(organisme_id=..., categorie=..., numero_equipe=...). "
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


@mcp.tool(name="ffbb_version", annotations=_READONLY_ANNOTATIONS)
async def ffbb_version() -> dict[str, Any]:
    """Informations de version et configuration runtime du serveur FFBB MCP.

    Retourne une structure compacte et strictement typée, pratique pour les
    agents et les outils de supervision.
    """
    return {
        "package_version": _PACKAGE_VERSION,
        "python_version": platform.python_version(),
        "cache_ttls": get_cache_ttls(),
    }


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
    id: Annotated[
        int, Field(description="Identifiant numerique de la ressource FFBB.")
    ],
    type: Annotated[
        Literal[
            "competition",
            "poule",
            "organisme",
        ],
        Field(description="Type de ressource a charger."),
    ],
    force_refresh: Annotated[
        bool,
        Field(
            description=(
                "Si True et type='poule', contourne le cache pour recuperer la poule "
                "en temps reel (scores live)."
            )
        ),
    ] = False,
) -> dict[str, Any]:
    """Recupere une ressource FFBB par identifiant.

    - `type="competition"` equivaut a `get_competition`.
    - `type="poule"` charge la poule (classements + rencontres) via l'API FFBB.
    - `type="organisme"` charge les details d'un club.

    Avertissement: ne pas utiliser pour obtenir un score ou un prochain match.
    Utiliser `ffbb_last_result` et `ffbb_next_match` a la place.
    """
    try:
        if type == "competition":
            return await get_competition_service(competition_id=id)
        elif type == "poule":
            poule_data = await get_poule_service(id, force_refresh=force_refresh)
            return {
                "id": poule_data.get("id"),
                "nom": poule_data.get("libelle"),
                "classements": poule_data.get("classements", []),
                "rencontres": poule_data.get("rencontres", []),
            }
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
        Literal[
            "calendrier",
            "equipes",
            "classement",
        ],
        Field(description="Action a effectuer pour le club."),
    ],
    club_name: Annotated[
        str | None,
        Field(
            description=(
                "Nom du club (recommande, ex: 'Stade Clermontois'). Si absent, "
                "`organisme_id` doit etre fourni."
            )
        ),
    ] = None,
    organisme_id: Annotated[
        int | None,
        Field(
            description=(
                "Identifiant FFBB du club. Si absent, `club_name` est utilise pour "
                "effectuer une recherche."
            )
        ),
    ] = None,
    filtre: Annotated[
        str | None,
        Field(
            description=(
                "Filtre facultatif de categorie/genre (ex: 'U11', 'U11M', 'U11F'). "
                "Utilise pour restreindre les equipes et poules."
            )
        ),
    ] = None,
    poule_id: Annotated[
        int | None,
        Field(
            description=(
                "Identifiant de la poule (obligatoire pour action='classement' si "
                "aucun filtre ne permet de determiner la poule)."
            )
        ),
    ] = None,
    phase: Annotated[
        str | None,
        Field(
            description=(
                "Nom ou numéro de la phase (ex: 'Phase 3', '2'). "
                "Utilisé avec action='classement' pour auto-résoudre la poule."
            )
        ),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(
            description=(
                "Si True, contourne le cache pour les donnees de calendrier ou "
                "de classement (utile les jours de match)."
            )
        ),
    ] = False,
) -> list[dict[str, Any]]:
    """Outils agreges autour d'un club (calendrier, equipes, classement).

    Avertissement: ne pas utiliser pour obtenir un score ou un prochain match
    d'une equipe specifique. Utiliser `ffbb_last_result` et `ffbb_next_match` a la place.
    """
    try:
        # Résolution automatique de l'organisme_id si manquant mais club_name fourni
        target_org_id = organisme_id
        if not target_org_id and club_name:
            # On cherche plusieurs candidats pour détecter l'ambiguïté
            orgs = await search_organismes_service(nom=club_name, limit=3)
            
            if not orgs:
                return [{"error": f"Aucun club trouvé pour '{club_name}'. Vérifie l'orthographe ou utilise ffbb_search."}]
            
            if len(orgs) > 1:
                # Ambiguïté détectée : plusieurs candidats
                candidates = [
                    {
                        "id": o.get("id"), 
                        "nom": o.get("nom"), 
                        "ville": o.get("ville_salle") or o.get("ville")
                    } 
                    for o in orgs if isinstance(o, dict)
                ]
                return [{
                    "error": f"Plusieurs clubs correspondent à '{club_name}'. Précise l'organisme_id ou un nom plus exact.",
                    "candidates": candidates
                }]
            
            if orgs and isinstance(orgs[0], dict):
                target_org_id = orgs[0].get("id")

        if action == "calendrier":
            if not target_org_id and not club_name:
                return [{"error": "Fournir organisme_id ou club_name"}]
            return await get_calendrier_club_service(
                club_name=club_name,
                organisme_id=target_org_id,
                categorie=filtre,
                force_refresh=force_refresh,
            )
        elif action == "equipes":
            if not target_org_id:
                return [{"error": "organisme_id requis pour l'action 'equipes' (la résolution du club_name a échoué)."}]
            return await ffbb_equipes_club_service(
                organisme_id=target_org_id, filtre=filtre
            )
        elif action == "classement":
            effective_poule_id = poule_id
            target_num = None

            # Auto-résolution du poule_id si manquant mais club/filtre présents
            if not effective_poule_id and target_org_id and filtre:
                # Parse le filtre pour extraire le numéro d'équipe si présent (ex: U11M1)
                from .utils import parse_categorie
                parsed = parse_categorie(filtre)
                target_num = parsed.numero_equipe if parsed else None
                
                # Tentative de résolution de la poule via le service dédié
                resolved_pid = await resolve_poule_id_service(
                    target_org_id, 
                    filtre, 
                    phase_query=phase
                )
                if resolved_pid:
                    effective_poule_id = resolved_pid

            if not effective_poule_id:
                return [{"error": "poule_id requis pour action='classement' (auto-résolution échouée - indique la phase ou vérifie l'ID de poule)"}]
            
            return await ffbb_get_classement_service(
                poule_id=effective_poule_id,
                force_refresh=force_refresh,
                target_organisme_id=target_org_id,
                target_num=target_num
            )
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
# TOOL 7 — Résolution d'équipe
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_resolve_team", annotations=_READONLY_ANNOTATIONS)
async def ffbb_resolve_team(
    club_name: Annotated[
        str | None,
        Field(description="Nom du club (ex: 'Stade Clermontois', 'ASVEL')."),
    ] = None,
    organisme_id: Annotated[
        int | str | None,
        Field(description="ID FFBB du club (alternative plus rapide à club_name)."),
    ] = None,
    categorie: Annotated[
        str,
        Field(
            description=(
                "Catégorie + genre + numéro d'équipe (ex: 'U11M1', 'U13F2', 'U15M'). "
                "Utilise les mêmes conventions que ffbb_bilan."
            ),
        ),
    ] = "U11M1",
) -> dict[str, Any]:
    """Identifie une equipe unique (Pivot central).

    DOIT etre utilise avant `ffbb_next_match` ou `ffbb_last_result` si l'agent
    ne connait pas le numero d'equipe exact ou si la categorie est ambiguë (ex: 'U11M').
    """
    return await ffbb_resolve_team_service(
        club_name=club_name, organisme_id=organisme_id, categorie=categorie
    )


# ---------------------------------------------------------------------------
# TOOL 8 — Résumé d'équipe (bilan + prochain/dernier match)
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_team_summary", annotations=_READONLY_ANNOTATIONS)
async def ffbb_team_summary(
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
            description="Catégorie + genre + numéro d'équipe (ex: 'U11M1', 'U13F2', 'U15M', 'Senior').",
        ),
    ] = None,
) -> dict[str, Any]:
    """Résumé complet et agent-friendly pour une équipe.

    Combine en UN seul appel :
      - bilan global (toutes phases)
      - phase courante et son classement
      - dernier match joué
      - prochain match à venir

    Recommandé pour répondre à des questions du type :
      - "Quel est le bilan de X cette saison ?"
      - "Quel est le prochain match de X ?"
      - "Quel a été le dernier résultat de X ?".
    """
    try:
        # Résoudre l'équipe d'abord pour obtenir organisme_id et catégorie
        resolve_result = await ffbb_resolve_team_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
        )

        resolved_team = resolve_result.get("team")
        club_resolu = resolve_result.get("club_resolu")
        resolved_org_id = club_resolu.get("organisme_id") if club_resolu else organisme_id
        resolved_num = 1
        if resolved_team:
            try:
                resolved_num = int(resolved_team.get("numero_equipe") or 1)
            except (TypeError, ValueError):
                resolved_num = 1

        # last_result et next_match nécessitent organisme_id
        effective_org_id = resolved_org_id

        # Lancer bilan + last_result + next_match en parallèle
        # On passe effective_org_id au lieu de club_name pour éviter une double résolution
        bilan_coro = ffbb_bilan_service(
            club_name=None,
            organisme_id=effective_org_id,
            categorie=categorie,
        )

        if effective_org_id and categorie:
            last_coro = ffbb_last_result_service(
                organisme_id=int(effective_org_id),
                categorie=categorie,
                numero_equipe=resolved_num,
            )
            next_coro = ffbb_next_match_service(
                organisme_id=effective_org_id,
                categorie=categorie,
                numero_equipe=resolved_num,
            )
            bilan, last_match, next_match = await asyncio.gather(
                bilan_coro, last_coro, next_coro, return_exceptions=True
            )
            # Normaliser les exceptions en dicts d'erreur
            if isinstance(bilan, Exception):
                bilan = {"error": str(bilan)}
            if isinstance(last_match, Exception):
                last_match = None
            if isinstance(next_match, Exception):
                next_match = None
        else:
            bilan = await bilan_coro
            last_match = None
            next_match = None

        return {
            "team": resolved_team or bilan.get("team"),
            "phase_courante": bilan.get("phase_courante"),
            "last_match": last_match,
            "next_match": next_match,
            "summary": bilan.get("bilan_total"),
            "raw": bilan,
        }
    except Exception as e:
        logger.error(f"ffbb_team_summary failed: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# TOOL 9 — Dernier résultat
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_last_result", annotations=_READONLY_ANNOTATIONS)
async def ffbb_last_result(
    categorie: Annotated[
        str,
        Field(description="Catégorie de l'équipe (ex: 'U11', 'U11M', 'U11F')"),
    ],
    club_name: Annotated[
        str | None, Field(description="Nom du club (ex: 'Stade Clermontois')")
    ] = None,
    organisme_id: Annotated[
        int | None,
        Field(description="Identifiant FFBB du club (organisme_id)")
    ] = None,
    numero_equipe: Annotated[
        int,
        Field(description="Numéro d'equipe dans la categorie (1 par defaut)"),
    ] = 1,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force un rafraichissement des donnees de poule"),
    ] = False,
) -> dict[str, Any]:
    """Dernier résultat d'une équipe précise.

    Recommendation LLM : Si la categorie est imprécise ou sans numéro (ex: 'U11M'),
    appeler d'abord `ffbb_resolve_team` pour obtenir le `numero_equipe` reel.
    """

    if club_name is None and organisme_id is None:
        return {
            "error": "Veuillez fournir club_name ou organisme_id pour trouver l'équipe."
        }

    return await ffbb_last_result_service(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        numero_equipe=numero_equipe,
        force_refresh=force_refresh,
    )


# ---------------------------------------------------------------------------
# TOOL 10 — Prochain match
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_next_match", annotations=_READONLY_ANNOTATIONS)
async def ffbb_next_match(
    categorie: Annotated[
        str, Field(description="Catégorie de l'équipe (ex: 'U11', 'U11M', 'U11F')")
    ],
    club_name: Annotated[
        str | None, Field(description="Nom du club (ex: 'Stade Clermontois')")
    ] = None,
    organisme_id: Annotated[
        int | None, Field(description="Identifiant FFBB du club (organisme_id)")
    ] = None,
    numero_equipe: Annotated[
        int, Field(description="Numéro d'equipe dans la categorie (1 par defaut)")
    ] = 1,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force un rafraichissement des donnees de poule"),
    ] = False,
) -> dict[str, Any]:
    """Prochain match à jouer pour une équipe précise.

    Recommendation LLM : Si la categorie est imprécise ou sans numéro (ex: 'U11M'),
    appeler d'abord `ffbb_resolve_team` pour obtenir le `numero_equipe` reel.
    """

    if club_name is None and organisme_id is None:
        return {
            "status": "error",
            "message": "Veuillez fournir club_name ou organisme_id pour trouver l'équipe.",
        }

    return await ffbb_next_match_service(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        numero_equipe=numero_equipe,
        force_refresh=force_refresh,
    )


# ---------------------------------------------------------------------------
# TOOL 11 — Bilan de saison
# ---------------------------------------------------------------------------


@mcp.tool(name="ffbb_bilan_saison", annotations=_READONLY_ANNOTATIONS)
async def ffbb_bilan_saison(
    organisme_id: Annotated[
        int | str,
        Field(description="ID FFBB du club (organisme) concerné."),
    ],
    categorie: Annotated[
        str,
        Field(
            description=(
                "Catégorie + genre (ex: 'U11M', 'U13F', 'SeniorM'). "
                "Cette valeur sert à filtrer les engagements et les poules."
            ),
        ),
    ],
    numero_equipe: Annotated[
        int,
        Field(
            description=(
                "Numéro d'équipe (1, 2, ...) pour identifier l'équipe précise dans la catégorie."
            )
        ),
    ],
) -> dict[str, Any]:
    """Bilan détaillé de la saison pour une équipe précise (toutes phases).

    Cet outil est optimisé pour les questions du type
    "Quel est le bilan de la saison des U11M1 ?".

    Il agrège toutes les phases (toutes poules) de la saison FFBB pour
    l'équipe identifiée par (organisme_id, categorie, numero_equipe).

    Pour chaque phase, il retourne :
      - competition
      - poule_id
      - position
      - match_joues, gagnes, perdus, nuls
      - paniers_marques, paniers_encaissés, difference

    Et fournit également un champ `bilan_total` qui cumule toutes les phases.
    """
    try:
        return await ffbb_saison_bilan_service(
            organisme_id=organisme_id,
            categorie=categorie,
            numero_equipe=numero_equipe,
        )
    except Exception as e:
        logger.error("ffbb_bilan_saison failed: %s", e)
        return {"error": str(e)}


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
        logger.info(f"Démarrage MCP FFBB en mode SSE standard sur {host}:{port}...")

        # Configuration des chemins pour éviter les conflits et erreurs 405
        # /mcp pour le flux SSE (GET), /mcp/messages pour les commandes (POST)
        mcp.settings.sse_path = "/mcp"
        mcp.settings.message_path = "/mcp/messages"

        # Création de l'application Starlette manuelle pour injecter les middlewares
        # essentiels en production (HTTPS derrière proxy, CORS)
        app = Starlette(debug=False)

        # Middleware pour gérer les headers de proxy (X-Forwarded-Proto pour HTTPS)
        # Indispensable pour que le serveur sache qu'il est en HTTPS derrière Nginx
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

        # Middleware CORS pour autoriser les clients MCP (web ou desktop)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Content-Type", "Authorization"],
        )

        # Montage du serveur MCP (SSE)
        app.mount("/", mcp.sse_app())

        import uvicorn
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        logger.info("Démarrage MCP FFBB en mode stdio...")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
