import asyncio
import datetime
import logging
import os
import platform
from functools import wraps
from importlib.metadata import PackageNotFoundError as _PkgNotFound
from importlib.metadata import version as _meta_version
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
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
    handle_api_error,
    multi_search_service,
    resolve_poule_id_service,
    search_competitions_service,
    search_engagements_service,
    search_formations_service,
    search_organismes_service,
    search_pratiques_service,
    search_rencontres_service,
    search_salles_service,
    search_terrains_service,
    search_tournois_service,
)
from .utils import prune_payload


def zipai_surgical(func: Any) -> Any:
    """Injecte la directive ZipAI et élague le payload retourné."""
    if func.__doc__:
        func.__doc__ += "\\n\\n    [ZIPAI DIRECTIVE: Output technical data only. No filler, no echo, no meta.]"
    else:
        func.__doc__ = "[ZIPAI DIRECTIVE: Output technical data only. No filler, no echo, no meta.]"

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        res = await func(*args, **kwargs)
        return prune_payload(res)

    return wrapper


def _find_website_dir() -> Path:
    """Détecte le dossier website/ en local ou en production."""
    # 1. Mode repo (src/ffbb_mcp/server.py -> ../../website)
    repo_path = Path(__file__).resolve().parents[2] / "website"
    if repo_path.exists():
        return repo_path
    # 2. Mode package (par exemple si website/ est copié au même niveau que src/)
    pkg_path = Path(__file__).resolve().parent / "website"
    if pkg_path.exists():
        return pkg_path
    # 3. Fallback sur le dossier de travail courant
    return Path.cwd() / "website"


_WEBSITE_DIR = _find_website_dir()
_DEFAULT_PUBLIC_URL = "https://ffbb.desimone.fr"
_REMOTE_LOGO_URL = (
    "https://raw.githubusercontent.com/nickdesi/FFBB-MCP-Server/main/assets/logo.webp"
)
_LOGO_PATH = _WEBSITE_DIR / "logo.webp"

logger = logging.getLogger("ffbb-mcp")

_READONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def _sdk_version(package: str) -> str:
    """Retourne la version installée d'un package Python (stdlib-only)."""
    try:
        return _meta_version(package)
    except _PkgNotFound:
        return "unknown"


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Initialisation FastMCP
# ---------------------------------------------------------------------------

_allowed_hosts = os.environ.get("ALLOWED_HOSTS", "*").split(",")
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
_dns_protection = os.environ.get("ENABLE_DNS_PROTECTION", "false").lower() == "true"

mcp: FastMCP = FastMCP(
    "FFBB MCP Server",
    instructions=(
        "Données FFBB (basketball français). "
        "⚡ OUTIL PRIORITAIRE pour tout bilan/résultats/classement : ffbb_bilan(club_name=..., categorie=...) "
        "→ 1 seul appel, retourne tout (toutes phases agrégées). "
        "Pour le bilan détaillé d'une équipe précise (U11M1, etc.), utiliser ffbb_bilan_saison(organisme_id=..., categorie=..., numero_equipe=...). "
        "Pour le prochain match d'une équipe précise, utiliser ffbb_next_match(organisme_id=..., categorie=..., numero_equipe=...). "
        "⚠️ Les données FFBB sont TOUJOURS live — ne jamais chercher en mémoire/cache avant d'appeler l'API. "
        "Autres outils : ffbb_search → trouver un club/compétition. "
        "ffbb_get(type='poule') → idéal pour LE CLASSEMENT uniquement. "
        "ffbb_club(action='calendrier') → calendrier exhaustif (pas de troncature). "
        "Règles : catégorie sans genre → demander M ou F. Plusieurs équipes même catégorie → demander laquelle.\n\n"
        "## Règle : Matchs restants d'une équipe\n"
        "Pour répondre à 'combien de matchs restent-il à [équipe] ?', NE PAS se contenter de ffbb_get(type='poule') "
        "car les données peuvent être tronquées (_omitted_count > 0).\n"
        "Workflow obligatoire :\n"
        "1. ffbb_team_summary → identifier poule_id, dernière journée jouée.\n"
        "2. ffbb_club(action='calendrier', filtre='<categorie>') → calendrier complet du club, "
        "puis filtrer les rencontres non jouées."
    ),
    dependencies=["mcp", "ffbb-api-client-v3"],
    # Streamable HTTP transport (MCP spec 2025-11-25)
    # stateless_http=True → pas de session persistante (scalabilité horizontale)
    # json_response=True  → répond en application/json (plus simple que SSE pour POST)
    stateless_http=True,
    json_response=True,
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
    index_path = _WEBSITE_DIR / "index.html"
    if index_path.exists():
        try:
            return index_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read index.html: {e}")

    # Fallback minimal au cas où le fichier est manquant
    return (
        "<html><body><h1>FFBB MCP Server</h1><p>Site en maintenance.</p></body></html>"
    )


def _build_robots_txt() -> str:
    base_url = _get_public_base_url()
    return f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n"


def _build_sitemap_xml() -> str:
    canonical_url = f"{_get_public_base_url()}/"
    lastmod = datetime.date.today().isoformat()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{canonical_url}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""


def _logo_response() -> Response:
    if _LOGO_PATH.exists():
        return FileResponse(_LOGO_PATH, media_type="image/webp")
    return RedirectResponse(_REMOTE_LOGO_URL)


@mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok", "service": "ffbb-mcp"})


@mcp.custom_route("/metrics", methods=["GET"])  # type: ignore[untyped-decorator]
async def metrics(request: Request) -> Response:
    return PlainTextResponse(generate_prometheus_metrics())


@mcp.custom_route("/logo.webp", methods=["GET"])  # type: ignore[untyped-decorator]
async def logo(request: Request) -> Response:
    return _logo_response()


@mcp.custom_route("/favicon.ico", methods=["GET"])  # type: ignore[untyped-decorator]
async def favicon(request: Request) -> Response:
    return _logo_response()


@mcp.custom_route("/css/style.css", methods=["GET"])  # type: ignore[untyped-decorator]
async def style_css(request: Request) -> Response:
    css_path = _WEBSITE_DIR / "css" / "style.css"
    if css_path.exists():
        return FileResponse(css_path, media_type="text/css")
    return Response("/* CSS non trouvé */", status_code=404)


@mcp.custom_route("/robots.txt", methods=["GET"])  # type: ignore[untyped-decorator]
async def robots_txt(request: Request) -> Response:
    return PlainTextResponse(_build_robots_txt())


@mcp.custom_route("/sitemap.xml", methods=["GET"])  # type: ignore[untyped-decorator]
async def sitemap_xml(request: Request) -> Response:
    return Response(_build_sitemap_xml(), media_type="application/xml")


@mcp.custom_route("/", methods=["GET"])  # type: ignore[untyped-decorator]
async def index(request: Request) -> Response:
    return HTMLResponse(content=_build_index_html(), status_code=200)


@mcp.tool(
    name="ffbb_version",
    title="Version et diagnostics serveur",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
async def ffbb_version() -> dict[str, Any]:
    """Informations de version et configuration runtime du serveur FFBB MCP.

    Retourne une structure compacte et strictement typée, pratique pour les
    agents et les outils de supervision.
    """
    mode = os.environ.get("MCP_MODE", "stdio").lower()
    return {
        "package_version": _PACKAGE_VERSION,
        "mcp_sdk_version": _sdk_version("mcp"),
        "python_version": platform.python_version(),
        "transport": "streamable-http"
        if mode in ("sse", "http", "streamable-http")
        else "stdio",
        "cache_ttls": get_cache_ttls(),
    }


# ---------------------------------------------------------------------------
# TOOL 1 — Recherche unifiée (remplace 8 tools de search)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_search",
    title="Recherche FFBB unifiée",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
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
            "engagements",
            "formations",
        ],
        Field(description="Type de données. 'all' cherche partout (défaut)."),
    ] = "all",
    limit: Annotated[int, Field(default=20, ge=1, le=100)] = 20,
    filter_by: Annotated[
        str | None,
        Field(description="Filtre Meilisearch natif (ex: 'codePostal = \"63000\"')."),
    ] = None,
    sort: Annotated[
        list[str] | None,
        Field(description="Tri Meilisearch natif (ex: ['libelle:asc'])."),
    ] = None,
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
            "engagements": search_engagements_service,
            "formations": search_formations_service,
        }
        return await dispatch[type](
            nom=query, limit=limit, filter_by=filter_by, sort=sort
        )
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 2 — Bilan complet toutes phases (1 appel = tout le workflow)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_bilan",
    title="Bilan complet toutes phases",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
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
    force_refresh: Annotated[
        bool,
        Field(
            description="Si True, contourne le cache pour récupérer des données fraîches."
        ),
    ] = False,
    ctx: Context[Any, Any, Any] | None = None,
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
        if ctx:
            await ctx.report_progress(0, total=3, message="Résolution du club…")
        result = await ffbb_bilan_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
            force_refresh=force_refresh,
        )
        if ctx:
            await ctx.report_progress(3, total=3, message="Bilan prêt.")
        return result
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 3 — Détails par ID (remplace get_competition + get_poule + get_organisme)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_get",
    title="Ressource FFBB par identifiant",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
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
    - `type="poule"` charge la poule (classements + rencontres).
    - `type="organisme"` charge les details d'un club.

    ⚠️ Attention: `type="poule"` peut être tronqué si la poule est grande.
    Pour un calendrier exhaustif, préférez `ffbb_club(action="calendrier")`.

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
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 4 — Club unifié (remplace get_equipes_club + get_classement + get_calendrier_club)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_club", title="Outils agrégés club", annotations=_READONLY_ANNOTATIONS
)
@zipai_surgical
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
    numero_equipe: Annotated[
        int | None,
        Field(
            description=(
                "Numéro d'équipe facultatif (ex: 1, 2, 3). "
                "Utilisé avec action='calendrier' pour ne récupérer que les matchs de cette équipe précise."
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

    ⚡ `action="calendrier"` est l'outil le plus fiable pour obtenir TOUTES les rencontres
    passées et futures d'une équipe/catégorie, sans les limitations de `ffbb_get(poule)`.

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
                return [
                    {
                        "error": f"Aucun club trouvé pour '{club_name}'. Vérifie l'orthographe ou utilise ffbb_search."
                    }
                ]

            if len(orgs) > 1:
                # Ambiguïté détectée : plusieurs candidats
                candidates = [
                    {
                        "id": o.get("id"),
                        "nom": o.get("nom"),
                        "ville": o.get("ville_salle") or o.get("ville"),
                    }
                    for o in orgs
                    if isinstance(o, dict)
                ]
                return [
                    {
                        "error": f"Plusieurs clubs correspondent à '{club_name}'. Précise l'organisme_id ou un nom plus exact.",
                        "candidates": candidates,
                    }
                ]

            if orgs and isinstance(orgs[0], dict):
                target_org_id = orgs[0].get("id")

        if action == "calendrier":
            if not target_org_id and not club_name:
                return [{"error": "Fournir organisme_id ou club_name"}]
            return await get_calendrier_club_service(
                club_name=club_name,
                organisme_id=target_org_id,
                categorie=filtre,
                numero_equipe=numero_equipe,
                force_refresh=force_refresh,
            )
        elif action == "equipes":
            if not target_org_id:
                return [
                    {
                        "error": "organisme_id requis pour l'action 'equipes' (la résolution du club_name a échoué)."
                    }
                ]
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
                    target_org_id, filtre, phase_query=phase
                )
                if resolved_pid:
                    effective_poule_id = int(resolved_pid)

            if not effective_poule_id:
                if phase:
                    return [
                        {
                            "error": (
                                f"Aucune poule trouvée pour la phase '{phase}' "
                                f"(filtre: '{filtre}'). "
                                "Vérifie le numéro de phase ou utilise ffbb_club(action='equipes') "
                                "pour lister les phases et poule_ids disponibles."
                            )
                        }
                    ]
                return [
                    {
                        "error": "poule_id requis pour action='classement' (auto-résolution échouée - indique la phase ou vérifie l'ID de poule)"
                    }
                ]

            return await ffbb_get_classement_service(
                poule_id=effective_poule_id,
                force_refresh=force_refresh,
                target_organisme_id=target_org_id,
                target_num=target_num,
            )
        return [{"error": f"Action inconnue: {action}"}]
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 5 — Scores en direct
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_lives", title="Scores en direct", annotations=_READONLY_ANNOTATIONS
)
@zipai_surgical
async def ffbb_get_lives() -> list[dict[str, Any]]:
    """Matchs en cours (scores live, cache 30s). Retourne [] si aucun match."""
    try:
        return await get_lives_service()
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 6 — Saisons
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_saisons",
    title="Liste des saisons FFBB",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
async def ffbb_get_saisons(
    active_only: Annotated[
        bool, Field(description="True = saison active uniquement.")
    ] = False,
) -> list[dict[str, Any]]:
    """Liste des saisons FFBB. active_only=True pour la saison en cours uniquement."""
    try:
        return await get_saisons_service(active_only=active_only)
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 7 — Résolution d'équipe
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_resolve_team",
    title="Résolution d’équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
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
    try:
        return await ffbb_resolve_team_service(
            club_name=club_name, organisme_id=organisme_id, categorie=categorie
        )
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 8 — Résumé d'équipe (bilan + prochain/dernier match)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_team_summary",
    title="Résumé complet d’équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
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
    ctx: Context[Any, Any, Any] | None = None,
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
        if ctx:
            await ctx.report_progress(0, total=3, message="Résolution de l'équipe…")
        # Résoudre l'équipe d'abord pour obtenir organisme_id et catégorie
        resolve_result = await ffbb_resolve_team_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
        )

        resolved_team = resolve_result.get("team")
        club_resolu = resolve_result.get("club_resolu")
        resolved_org_id = (
            club_resolu.get("organisme_id") if club_resolu else organisme_id
        )
        resolved_num = 1
        if resolved_team:
            try:
                resolved_num = int(resolved_team.get("numero_equipe") or 1)
            except (TypeError, ValueError):
                resolved_num = 1

        # last_result et next_match nécessitent organisme_id
        effective_org_id = resolved_org_id

        if ctx:
            await ctx.report_progress(
                1, total=3, message="Récupération bilan et matchs en parallèle…"
            )

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

        if ctx:
            await ctx.report_progress(3, total=3, message="Résumé prêt.")
        return {
            "team": resolved_team or bilan.get("team"),
            "phase_courante": bilan.get("phase_courante"),
            "last_match": last_match,
            "next_match": next_match,
            "summary": bilan.get("bilan_total"),
        }
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 9 — Dernier résultat
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_last_result",
    title="Dernier résultat d’équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
async def ffbb_last_result(
    categorie: Annotated[
        str,
        Field(description="Catégorie de l'équipe (ex: 'U11', 'U11M', 'U11F')"),
    ],
    club_name: Annotated[
        str | None, Field(description="Nom du club (ex: 'Stade Clermontois')")
    ] = None,
    organisme_id: Annotated[
        int | None, Field(description="Identifiant FFBB du club (organisme_id)")
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
            "status": "error",
            "message": "Veuillez fournir club_name ou organisme_id pour trouver l'équipe.",
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


@mcp.tool(
    name="ffbb_next_match",
    title="Prochain match d’équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
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

    ⚠️ ATTENTION LLM : Cet outil retourne STRICTEMENT LE PROCHAIN MATCH UNIQUE.
    Ne l'utilise JAMAIS si l'utilisateur demande "les prochains matchs" au pluriel.
    Pour toute requête au pluriel, utilise OBLIGATOIREMENT `ffbb_club(action="calendrier")`
    et filtre les résultats toi-même.

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


@mcp.tool(
    name="ffbb_bilan_saison",
    title="Bilan détaillé de saison",
    annotations=_READONLY_ANNOTATIONS,
)
@zipai_surgical
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
    force_refresh: Annotated[
        bool,
        Field(
            description="Si True, contourne le cache pour récupérer des données fraîches."
        ),
    ] = False,
    ctx: Context[Any, Any, Any] | None = None,
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
        if ctx:
            await ctx.report_progress(0, total=1, message="Calcul du bilan saison…")
        result = await ffbb_saison_bilan_service(
            organisme_id=organisme_id,
            categorie=categorie,
            numero_equipe=numero_equipe,
            force_refresh=force_refresh,
        )
        if ctx:
            await ctx.report_progress(1, total=1, message="Bilan saison prêt.")
        return result
    except Exception as e:
        raise handle_api_error(e) from e


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

    if mode in ("sse", "http", "streamable-http"):
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "9123"))
        logger.info(
            f"Démarrage MCP FFBB en mode Streamable HTTP sur {host}:{port}/mcp ..."
        )

        mcp.settings.streamable_http_path = "/mcp"
        from ffbb_mcp.app_factory import create_app
        from ffbb_mcp.http_routes import register_http_routes

        register_http_routes(mcp)
        app = create_app(mcp, _allowed_origins)

        import uvicorn

        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        logger.info("Démarrage MCP FFBB en mode stdio...")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
