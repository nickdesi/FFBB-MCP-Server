# Note mypy: les `# type: ignore[untyped-decorator]` sur `@mcp.tool(...)`
# dans ce fichier proviennent du décorateur FastMCP dont les stubs
# officiels ne sont pas typés. Convention documentée au niveau du projet.

import asyncio
import logging
import os
import platform
import re
import urllib.parse
from functools import wraps
from importlib.metadata import PackageNotFoundError as _PkgNotFound
from importlib.metadata import version as _meta_version
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from ffbb_mcp.models import BilanResponse, CalendrierMatch

from . import __version__ as _PACKAGE_VERSION
from .metrics import record_tool_call
from .prompts import ROUTING_PROMPT, register_prompts
from .resources import register_resources
from .routes import register_routes
from .services import (
    explain_tiebreak_rules_service,
    ffbb_bilan_service,
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    ffbb_head_to_head_service,
    ffbb_last_result_service,
    ffbb_next_match_service,
    ffbb_resolve_team_service,
    ffbb_saison_bilan_service,
    ffbb_search_service,
    find_team_poule_service,
    format_poule_response,
    get_cache_ttls,
    get_calendrier_club_service,
    get_competition_service,
    get_entraineur_service,
    get_lives_service,
    get_officiel_service,
    get_organisme_service,
    get_poule_service,
    get_regulation_article_service,
    get_rencontre_service,
    get_saisons_service,
    get_salle_service,
    handle_api_error,
    list_regulations_service,
    resolve_club_and_org,
    resolve_poule_id_service,
    search_regulations_service,
)
from .sse_patch import apply_fastmcp_json_formatting_patch
from .utils import parse_categorie, prune_payload


def zipai_surgical(func: Any) -> Any:
    """Élague le payload retourné (la directive ZipAI est passée en instruction globale)."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        res = await func(*args, **kwargs)
        if res is None:
            return []
        if isinstance(res, (str, int, float, bool)):
            return [] if res == "" else res
        if isinstance(res, list) and len(res) <= 5:
            return res
        if isinstance(res, dict) and len(res) <= 5:
            return res
        return prune_payload(res)

    return wrapper


def track_tool_usage(tool_name: str):
    """Décorateur léger pour compter les appels par outil MCP."""

    def decorator(func: Any) -> Any:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            record_tool_call(tool_name)
            return await func(*args, **kwargs)

        return wrapper

    return decorator


logger = logging.getLogger("ffbb-mcp")


def _resolve_log_level(raw: str | None) -> int:
    """Résout un niveau de log à partir d'une valeur d'environnement."""
    if not raw:
        return logging.INFO
    value = raw.strip().upper()
    mapping = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }
    return mapping.get(value, logging.INFO)


def _resolve_uvicorn_log_level(level: int) -> str:
    """Mappe le niveau Python vers un niveau uvicorn compatible."""
    if level <= logging.DEBUG:
        return "debug"
    if level <= logging.INFO:
        return "info"
    if level <= logging.WARNING:
        return "warning"
    if level <= logging.ERROR:
        return "error"
    return "critical"


async def _safe_report_progress(
    ctx: Context[Any, Any, Any] | None,
    progress: float,
    total: float | None = None,
    message: str | None = None,
) -> None:
    """Rapporte la progression à FastMCP sans casser en l'absence de request.

    FastMCP expose ``Context.request_context`` comme une ``@property`` qui
    lève ``ValueError`` hors d'un vrai request (ex: appels via
    ``mcp.call_tool`` en test unitaire). On capture donc un petit ensemble
    défensif d'exceptions et on no-op silencieusement — l'objectif est que
    le rapport de progression ne bloque JAMAIS l'exécution d'un outil.
    """
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress, total=total, message=message)
    except (ValueError, AssertionError):
        # Hors d'un vrai RequestContext FastMCP ou état dégradé → no-op
        # mais on trace en DEBUG pour ne pas perdre la trace d'un bug.
        logger.debug("progress report skipped", exc_info=True)


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

# Meilisearch filter_by: allow only printable non-control chars, block newlines/nulls.
_FILTER_BY_MAX_LEN = 500
_FILTER_BY_BLOCKED = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


def _validate_filter_by(filter_by: str | None) -> str | None:
    """Validates a Meilisearch filter expression from user input.

    Raises ValueError on obviously malicious input (newlines, null bytes).
    """
    if filter_by is None:
        return None
    if len(filter_by) > _FILTER_BY_MAX_LEN:
        raise ValueError(
            f"filter_by dépasse la longueur maximale ({_FILTER_BY_MAX_LEN} caractères)"
        )
    if _FILTER_BY_BLOCKED.search(filter_by):
        raise ValueError("filter_by contient des caractères de contrôle invalides")
    return filter_by


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

_public_url = os.environ.get("PUBLIC_URL", "https://ffbb.desimone.fr").strip()
try:
    _parsed_url = urllib.parse.urlparse(_public_url)
    _public_host = _parsed_url.hostname
except Exception:
    _public_host = "ffbb.desimone.fr"

_allowed_hosts_raw = os.environ.get("ALLOWED_HOSTS", "*")
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "*")
_allowed_hosts = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]
_allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

# Ajout automatique de l'hôte public et de l'origine publique par défaut
if _public_host and _public_host not in _allowed_hosts and "*" not in _allowed_hosts:
    _allowed_hosts.append(_public_host)

if _public_url and _public_url not in _allowed_origins and "*" not in _allowed_origins:
    _allowed_origins.append(_public_url)

# On ajoute localhost par défaut si pas de wildcard
if "*" not in _allowed_hosts and "localhost" not in _allowed_hosts:
    _allowed_hosts.append("localhost")

_dns_protection_env = os.environ.get("ENABLE_DNS_PROTECTION")
if _dns_protection_env is not None:
    _dns_protection = _dns_protection_env.lower() == "true"
else:
    # Désactivation automatique si wildcard présent (non supporté par le SDK MCP v1.x)
    _dns_protection = "*" not in _allowed_hosts and "*" not in _allowed_origins

mcp: FastMCP = FastMCP(
    "FFBB MCP Server",
    instructions=(
        ROUTING_PROMPT
        + "\n[ZIPAI: Données FFBB live. Format tableau classement strict (Rang, Équipe, PTS, J, G, P, M, E, Diff). Obligation formelle : repérer l'équipe ciblée (is_target=True) et mettre son nom en GRAS avec 🎯 : | Rang | **Nom Équipe** 🎯 | PTS | ... |. Pas de recalcul.]"
    ),
    dependencies=["mcp", "ffbb-data-client"],
    # Streamable HTTP transport (MCP spec 2025-11-25)
    # stateless_http=False → session persistante avec mcp-session-id
    #   (requis par Antigravity et la plupart des clients MCP)
    # json_response=True  → répond en application/json (plus simple que SSE pour POST)
    stateless_http=False,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=_dns_protection,
        allowed_hosts=_allowed_hosts,
        allowed_origins=_allowed_origins,
    ),
)


@mcp.tool(
    name="ffbb_version",
    title="Version et diagnostics serveur",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_version")
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
    title="Recherche FFBB (multi-index)",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_search")
@zipai_surgical
async def ffbb_search(
    query: Annotated[
        str,
        Field(
            description=("Texte libre (ex: 'Vichy', 'U13F Auvergne')."),
        ),
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
            "officiels",
            "entraineurs",
            "communes",
        ],
        Field(
            description=("Type de données. 'all' cherche partout (défaut)."),
        ),
    ] = "all",
    limit: Annotated[
        int,
        Field(description="Nombre maximum de résultats à retourner (1-100)."),
    ] = 20,
    offset: Annotated[
        int,
        Field(description="Index de départ pour pagination (défaut: 0)."),
    ] = 0,
    filter_by: Annotated[
        str | None,
        Field(
            description=(
                "Filtre Meilisearch natif (ex: 'codePostal = \"63000\"', "
                '\'codePostal IN ["63000", "63100"]\', \'departement = "Puy-de-Dôme"\').'
            )
        ),
    ] = None,
    sort: Annotated[
        list[str] | None,
        Field(description="Tri Meilisearch (ex: ['libelle:asc'])."),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force le rafraîchissement des données."),
    ] = False,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Recherche FFBB — clubs, compétitions, matchs, salles, tournois, etc.

    - type='all' → recherche globale (meilleur point d'entrée).
    - type='organismes' → clubs uniquement.
    - type='competitions' → compétitions uniquement.
    - type='salles' → salles / gymnases.
    - filter_by='codePostal = "63000"' → filtrage par code postal ou critères Meilisearch.

    Résultats contiennent un 'id' à utiliser avec ffbb_get ou ffbb_club.
    """
    try:
        safe_filter = _validate_filter_by(filter_by)
        # Délègue la logique détaillée au service dédié pour centraliser le dispatch
        return await ffbb_search_service(
            query=query,
            type=type,
            limit=limit,
            offset=offset,
            filter_by=safe_filter,
            sort=sort,
            force_refresh=force_refresh,
        )
    except ValueError as e:
        raise handle_api_error(e) from e
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
@track_tool_usage("ffbb_bilan")
@zipai_surgical
async def ffbb_bilan(
    organisme_id: Annotated[
        int | str | None,
        Field(
            description="ID FFBB du club (ex: '9326' ou 'ARA0063058'). Requis si club_name absent."
        ),
    ] = None,
    club_name: Annotated[
        str | None,
        Field(
            description="Nom du club (ex: 'Stade Clermontois', 'ASVEL'). Requis si organisme_id absent."
        ),
    ] = None,
    categorie: Annotated[
        str | None,
        Field(description="Catégorie/genre/numéro (ex: 'U11M1', 'Senior')."),
    ] = None,
    numero_equipe: Annotated[
        int | None,
        Field(description="Numéro d'équipe (ex: 1, 2)."),
    ] = None,
    engagement_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de l'engagement (prioritaire pour désambiguïser)."),
    ] = None,
    competition_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la compétition pour désambiguïser."),
    ] = None,
    competition_type: Annotated[
        str | None,
        Field(
            description="Type de compétition ('PLAT', 'COUPE', etc.) pour désambiguïser."
        ),
    ] = None,
    poule_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la poule pour désambiguïser."),
    ] = None,
    season_id: Annotated[
        int | str | None,
        Field(description="ID de la saison FFBB (optionnel)."),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, contourne le cache."),
    ] = False,
    ctx: Context[Any, Any, Any] | None = None,
) -> dict[str, Any] | BilanResponse:
    """Bilan complet d'une équipe toutes phases confondues en UN seul appel (V/D/N, paniers, phases).

    Outil prioritaire pour 'quel est le bilan de X ?' ou 'résultats de U11M1'.
    """
    try:
        await _safe_report_progress(ctx, 0, total=3, message="Résolution du club…")
        effective_refresh = force_refresh
        effective_cat = categorie
        if (
            numero_equipe is not None
            and numero_equipe > 1
            and categorie
            and str(numero_equipe) not in categorie
        ):
            effective_cat = f"{categorie}{numero_equipe}"

        result = await ffbb_bilan_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=effective_cat,
            engagement_id=engagement_id,
            competition_id=competition_id,
            competition_type=competition_type,
            poule_id=poule_id,
            season_id=season_id,
            force_refresh=effective_refresh,
        )
        await _safe_report_progress(ctx, 3, total=3, message="Bilan prêt.")
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
@track_tool_usage("ffbb_get")
@zipai_surgical
async def ffbb_get(
    id: Annotated[
        int | str,
        Field(
            description=(
                "Identifiant FFBB exact (string opaque, ex: '200000003057825'). Ne pas passer un nom de club: "
                "utiliser d'abord ffbb_search pour résoudre l'id."
            )
        ),
    ],
    type: Annotated[
        Literal[
            "competition",
            "poule",
            "organisme",
            "rencontre",
            "officiel",
            "entraineur",
            "salle",
        ],
        Field(description="Type de ressource a charger."),
    ],
    club: Annotated[
        str | None,
        Field(
            description=(
                "Nom ou ID du club à localiser dans les poules (si type='competition'). "
                "Permet de trouver directement l'ID et le nom de poule d'un club dans une compétition multi-poules."
            )
        ),
    ] = None,
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

    - `type="competition"` equivaut a `get_competition`. Si `club` est fourni, localise directement la poule du club au sein de la compétition.
    - `type="poule"` charge la poule (classements + rencontres).
    - `type="organisme"` charge les details d'un club.
    - `type="rencontre"` charge une rencontre précise.
    - `type="salle"` charge les details d'une salle et son adresse normalisée.

    ⚠️ Attention: `type="poule"` peut être tronqué si la poule est grande.
    Pour un calendrier exhaustif, préférez `ffbb_club(action="calendrier")`.

    Avertissement: ne pas utiliser pour obtenir un score ou un prochain match.
    Utiliser `ffbb_last_result` et `ffbb_next_match` a la place.
    """
    try:
        if type == "competition":
            if club:
                return await find_team_poule_service(
                    competition_id=id, organisme_id_or_name=club
                )
            return await get_competition_service(competition_id=id)
        elif type == "poule":
            effective_refresh = force_refresh
            poule_data = await get_poule_service(id, force_refresh=effective_refresh)
            return await format_poule_response(poule_data)
        elif type == "organisme":
            return await get_organisme_service(organisme_id=id)
        elif type == "rencontre":
            return await get_rencontre_service(id)
        elif type == "officiel":
            return await get_officiel_service(id)
        elif type == "entraineur":
            return await get_entraineur_service(id)
        elif type == "salle":
            return await get_salle_service(id)
        return {"error": f"Type inconnu: {type}"}
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 4 — Club unifié (remplace get_equipes_club + get_classement + get_calendrier_club)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_club", title="Outils agrégés club", annotations=_READONLY_ANNOTATIONS
)
@track_tool_usage("ffbb_club")
@zipai_surgical
async def ffbb_club(
    action: Annotated[
        Literal[
            "calendrier",
            "equipes",
            "classement",
        ],
        Field(
            description="Action : 'calendrier' (matchs pluriels/restants), 'equipes' ou 'classement'."
        ),
    ] = "calendrier",
    organisme_id: Annotated[
        int | str | None,
        Field(description="ID FFBB du club (ex: '9326'). Requis si club_name absent."),
    ] = None,
    club_name: Annotated[
        str | None,
        Field(
            description="Nom du club (ex: 'Stade Clermontois'). Requis si organisme_id absent."
        ),
    ] = None,
    categorie: Annotated[
        str | None,
        Field(
            description="Catégorie, division ou filtre d'équipe (alias pour 'filtre', ex: 'NM3', 'U15M', 'Senior').",
        ),
    ] = None,
    numero_equipe: Annotated[
        int | None,
        Field(
            description="Numéro d'équipe (ex: 1, 2) pour action='calendrier' ou 'classement'."
        ),
    ] = None,
    engagement_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de l'engagement (prioritaire pour désambiguïser)."),
    ] = None,
    competition_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la compétition pour désambiguïser."),
    ] = None,
    competition_type: Annotated[
        str | None,
        Field(
            description="Type de compétition ('PLAT', 'COUPE', etc.) pour désambiguïser."
        ),
    ] = None,
    poule_id: Annotated[
        int | str | None,
        Field(
            description="ID poule (action='classement' ou 'calendrier'). Optionnel si club et catégorie sont fournis."
        ),
    ] = None,
    season_id: Annotated[
        int | str | None,
        Field(description="ID de la saison FFBB (optionnel)."),
    ] = None,
    limit: Annotated[
        int | None,
        Field(
            description="Nombre max de matchs retournés (1-100, pagination).",
            ge=1,
            le=100,
        ),
    ] = None,
    offset: Annotated[
        int | None,
        Field(
            description="Index de départ pour pagination calendrier (défaut 0).",
            ge=0,
        ),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, contourne le cache."),
    ] = False,
    filtre: Annotated[
        str | None,
        Field(
            description="Filtre catégorie/genre (alias pour 'categorie', ex: 'U11M', 'Senior', 'NM3')."
        ),
    ] = None,
    adversaire: Annotated[
        str | None,
        Field(
            description="Nom adversaire pour filtrer les confrontations directes (action='calendrier')."
        ),
    ] = None,
    phase: Annotated[
        str | None,
        Field(description="Nom ou numéro de phase (ex: 'Phase 2')."),
    ] = None,
    date_debut: Annotated[
        str | None,
        Field(description="Date début YYYY-MM-DD (action='calendrier')."),
    ] = None,
    date_fin: Annotated[
        str | None,
        Field(description="Date fin YYYY-MM-DD (action='calendrier')."),
    ] = None,
) -> list[dict[str, Any]] | list[CalendrierMatch] | dict[str, Any]:
    """Outils agrégés club : calendrier (matchs pluriels), équipes engagées ou classement.

    Outil de référence pour toute demande au pluriel : matchs restants, calendrier complet.
    Pour une équipe senior au niveau national ou régional, la catégorie FFBB interne est souvent `SEM1` ou `SEF1` ;
    le serveur résout désormais `NM3`, `NM2`, `NF1`, `PNM`, `R2`, etc. vers la bonne équipe et sa poule.
    Pour action='classement', le poule_id est optionnel si club_name/organisme_id et categorie (ou filtre) sont fournis.
    Utiliser adversaire avec action='calendrier' pour isoler les confrontations directes.
    """
    try:
        effective_filtre = filtre or categorie

        # Action calendrier : le service gère résolution + ambiguïté en interne
        if action == "calendrier":
            if not organisme_id and not club_name:
                return [{"error": "Fournir organisme_id ou club_name"}]
            effective_refresh = force_refresh
            kwargs: dict[str, Any] = {
                "club_name": club_name,
                "organisme_id": organisme_id,
                "categorie": effective_filtre,
                "numero_equipe": numero_equipe,
                "adversaire": adversaire,
                "force_refresh": effective_refresh,
            }
            if date_debut is not None:
                kwargs["date_debut"] = date_debut
            if date_fin is not None:
                kwargs["date_fin"] = date_fin
            if limit is not None:
                kwargs["limit"] = limit
            if offset is not None:
                kwargs["offset"] = offset
            if engagement_id is not None:
                kwargs["engagement_id"] = engagement_id
            if competition_id is not None:
                kwargs["competition_id"] = competition_id
            if competition_type is not None:
                kwargs["competition_type"] = competition_type
            if season_id is not None:
                kwargs["season_id"] = season_id
            return await get_calendrier_club_service(**kwargs)

        # Actions equipes / classement : pré-résolution nécessaire
        target_org_id = organisme_id
        if not target_org_id and club_name:
            resolved_clubs, _ = await resolve_club_and_org(
                club_name=club_name,
                organisme_id=None,
                categorie=effective_filtre,
                limit=3,
            )

            if not resolved_clubs:
                return [
                    {
                        "error": f"Aucun club trouvé pour '{club_name}'. Vérifie l'orthographe ou utilise ffbb_search."
                    }
                ]

            if len(resolved_clubs) > 1:
                # Ambiguïté détectée : plusieurs candidats
                candidates = [
                    {
                        "id": c.get("organisme_id"),
                        "nom": c.get("nom"),
                        "ville": c.get("ville"),
                        "code_postal": c.get("code_postal"),
                        "departement": c.get("departement"),
                        "genre": c.get("genre"),
                    }
                    for c in resolved_clubs
                    if isinstance(c, dict)
                ]
                return [
                    {
                        "error": f"Plusieurs clubs correspondent à '{club_name}'. Précise l'organisme_id ou un nom plus exact.",
                        "candidates": candidates,
                    }
                ]

            target_org_id = resolved_clubs[0].get("organisme_id")

        if action == "equipes":
            if not target_org_id:
                return [
                    {
                        "error": "organisme_id requis pour l'action 'equipes' (la résolution du club_name a échoué)."
                    }
                ]
            result = await ffbb_equipes_club_service(
                organisme_id=target_org_id,
                filtre=effective_filtre,
                force_refresh=force_refresh,
            )
            if not result:
                return [
                    {
                        "status": "ok",
                        "message": f"Le club (organisme_id={target_org_id}) existe mais n'a pas d'équipes actives.",
                        "equipes": [],
                    }
                ]
            return result
        elif action == "classement":
            effective_poule_id = poule_id
            target_num = numero_equipe if numero_equipe and numero_equipe > 1 else None

            # Auto-résolution du poule_id si manquant mais club présent
            if not effective_poule_id and target_org_id:
                from .services.club import _parse_division_code
                from .utils import parse_categorie

                search_filtre = effective_filtre
                if (
                    numero_equipe
                    and numero_equipe > 1
                    and search_filtre
                    and str(numero_equipe) not in search_filtre
                ):
                    search_filtre = f"{search_filtre}{numero_equipe}"
                elif not search_filtre and numero_equipe:
                    search_filtre = str(numero_equipe)

                is_div = (
                    _parse_division_code(search_filtre) is not None
                    if search_filtre
                    else False
                )
                if not is_div and search_filtre:
                    parsed = parse_categorie(search_filtre)
                    if parsed and parsed.numero_equipe:
                        target_num = parsed.numero_equipe

                # Tentative de résolution de la poule via le service dédié
                resolved_pid = await resolve_poule_id_service(
                    target_org_id, search_filtre or "", phase_query=phase
                )
                if resolved_pid:
                    effective_poule_id = str(resolved_pid)

            if not effective_poule_id:
                if phase:
                    return [
                        {
                            "error": (
                                f"Aucune poule trouvée pour la phase '{phase}' "
                                f"(filtre: '{effective_filtre}'). "
                                "Vérifie le numéro de phase ou utilise ffbb_club(action='equipes') "
                                "pour lister les phases et poule_ids disponibles."
                            )
                        }
                    ]
                return [
                    {
                        "error": (
                            f"Impossible de résoudre automatiquement la poule pour ce club "
                            f"(filtre: '{effective_filtre}'). "
                            "Précise la catégorie (ex: categorie='NM3') ou utilise ffbb_club(action='equipes') "
                            "pour trouver l'identifiant exact de la poule (poule_id)."
                        )
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
@track_tool_usage("ffbb_lives")
@zipai_surgical
async def ffbb_get_lives(
    include_scheduled: Annotated[
        bool,
        Field(
            description=(
                "Si True, inclut aussi les matchs programmés à venir (statut SCHEDULED). "
                "Par défaut (False), ne retourne que les matchs réellement en cours de jeu."
            )
        ),
    ] = False,
) -> list[dict[str, Any]]:
    """Matchs en cours (scores live, rafraîchissement toutes les 15s). Retourne [] si aucun match."""
    try:
        return await get_lives_service(include_scheduled=include_scheduled)
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
@track_tool_usage("ffbb_saisons")
@zipai_surgical
async def ffbb_get_saisons(
    active_only: Annotated[
        bool, Field(description="True = saison active uniquement.")
    ] = False,
    force_refresh: Annotated[
        bool, Field(description="Si True, contourne le cache.")
    ] = False,
) -> list[dict[str, Any]]:
    """Liste des saisons FFBB (référentiel temporel).

    Utilise cet outil pour récupérer les `season_id` disponibles avant d'appeler
    `ffbb_bilan`, `ffbb_club` ou `ffbb_team_summary` avec un filtre de saison.
    Avec `active_only=True`, ne retourne que la saison en cours.
    Ne pas utiliser pour obtenir un classement, un calendrier ou un bilan — utilise
    `ffbb_club(action="classement")` ou `ffbb_bilan` à la place.
    """
    try:
        return await get_saisons_service(
            active_only=active_only, force_refresh=force_refresh
        )
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 7 — Résolution d'équipe
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_resolve_team",
    title="Résolution d'équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_resolve_team")
@zipai_surgical
async def ffbb_resolve_team(
    organisme_id: Annotated[
        int | str | None,
        Field(description="ID FFBB du club (alternative plus rapide à club_name)."),
    ] = None,
    club_name: Annotated[
        str | None,
        Field(description="Nom du club (ex: 'Stade Clermontois', 'ASVEL')."),
    ] = None,
    categorie: Annotated[
        str | None,
        Field(
            description=(
                "Catégorie + genre + numéro d'équipe (ex: 'U11M1', 'U13F2', 'SEM1') ou division (ex: 'NM3', 'R2', 'PNM'). "
                "Si le numéro manque, cet outil retourne la bonne équipe ou des candidats."
            ),
        ),
    ] = None,
    numero_equipe: Annotated[
        int | None,
        Field(description="Numéro d'équipe facultatif (ex: 1, 2)."),
    ] = None,
    engagement_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de l'engagement (prioritaire pour désambiguïser)."),
    ] = None,
    competition_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la compétition pour désambiguïser."),
    ] = None,
    competition_type: Annotated[
        str | None,
        Field(
            description="Type de compétition ('PLAT', 'COUPE', etc.) pour désambiguïser."
        ),
    ] = None,
    poule_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la poule pour désambiguïser."),
    ] = None,
    season_id: Annotated[
        int | str | None,
        Field(description="ID de la saison FFBB (optionnel)."),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force le rafraîchissement des données."),
    ] = False,
) -> dict[str, Any]:
    """Identifie une equipe unique (Pivot central).

    DOIT etre utilise avant `ffbb_next_match` ou `ffbb_last_result` si l'agent
    ne connait pas le numero d'equipe exact ou si la categorie est ambiguë (ex: 'U11M').
    Pour une équipe senior au niveau national ou régional, la catégorie FFBB interne est souvent `SEM1` ou `SEF1` ;
    le serveur résout désormais `NM3`, `NM2`, `NF1`, `PNM`, `R2`, etc. vers la bonne équipe et sa poule.
    """
    try:
        return await ffbb_resolve_team_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
            numero_equipe=numero_equipe,
            engagement_id=engagement_id,
            competition_id=competition_id,
            competition_type=competition_type,
            poule_id=poule_id,
            season_id=season_id,
            force_refresh=force_refresh,
        )
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 8 — Résumé d'équipe (bilan + prochain/dernier match)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_team_summary",
    title="Résumé complet d'équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_team_summary")
@zipai_surgical
async def ffbb_team_summary(
    organisme_id: Annotated[
        int | str | None,
        Field(description="ID FFBB du club (alternative plus rapide à club_name)."),
    ] = None,
    club_name: Annotated[
        str | None,
        Field(description="Nom du club (ex: 'Stade Clermontois', 'ASVEL')."),
    ] = None,
    categorie: Annotated[
        str | None,
        Field(
            description="Catégorie/division + genre + numéro d'équipe (ex: 'U11M1', 'U13F2', 'SEM1', 'NM3', 'PNM').",
        ),
    ] = None,
    numero_equipe: Annotated[
        int | None,
        Field(
            description="Numéro d'équipe dans la catégorie (ex: 1, 2).",
        ),
    ] = None,
    engagement_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de l'engagement (prioritaire pour désambiguïser)."),
    ] = None,
    competition_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la compétition pour désambiguïser."),
    ] = None,
    competition_type: Annotated[
        str | None,
        Field(
            description="Type de compétition ('PLAT', 'COUPE', etc.) pour désambiguïser."
        ),
    ] = None,
    poule_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la poule pour désambiguïser."),
    ] = None,
    season_id: Annotated[
        int | str | None,
        Field(description="ID de la saison FFBB (optionnel)."),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force un rafraichissement des donnees"),
    ] = False,
    ctx: Context[Any, Any, Any] | None = None,
) -> dict[str, Any]:
    """Résumé complet et agent-friendly pour une équipe.

    Combine en UN seul appel :
      - bilan global (toutes phases)
      - phase courante et son classement
      - dernier match joué
      - prochain match à venir

    Pour une équipe senior au niveau national ou régional, la catégorie FFBB interne est souvent `SEM1` ou `SEF1` ;
    le serveur résout désormais `NM3`, `NM2`, `NF1`, `PNM`, `R2`, etc. vers la bonne équipe et sa poule.
    Recommandé pour une vue rapide d'une équipe précise. Si la catégorie est ambiguë
    ou sans numéro d'équipe, l'outil tente une résolution via `ffbb_resolve_team`.
    Pour une liste de matchs restants, utiliser plutôt `ffbb_club(action="calendrier")`.
    """
    try:
        await _safe_report_progress(ctx, 0, total=3, message="Résolution de l'équipe…")
        parsed_cat = parse_categorie(categorie) if categorie else None
        effective_cat = categorie
        if (
            parsed_cat
            and parsed_cat.numero_equipe is None
            and numero_equipe is not None
        ):
            effective_cat = f"{categorie}{numero_equipe}"

        # Résoudre l'équipe d'abord pour obtenir organisme_id et catégorie
        resolve_result = await ffbb_resolve_team_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=effective_cat,
            numero_equipe=numero_equipe,
            engagement_id=engagement_id,
            competition_id=competition_id,
            competition_type=competition_type,
            poule_id=poule_id,
            season_id=season_id,
            force_refresh=force_refresh,
        )

        if resolve_result.get("status") in ("ambiguous", "not_found"):
            return resolve_result

        resolved_team = resolve_result.get("team")
        club_resolu = resolve_result.get("club_resolu")
        resolved_org_id = (
            club_resolu.get("organisme_id") if club_resolu else organisme_id
        )
        resolved_num = numero_equipe or 1
        if resolved_team:
            try:
                resolved_num = int(
                    resolved_team.get("numero_equipe") or numero_equipe or 1
                )
            except (TypeError, ValueError):  # fmt: skip
                resolved_num = numero_equipe or 1

        # last_result et next_match nécessitent organisme_id
        effective_org_id = resolved_org_id

        if not effective_org_id:
            return {"error": "Impossible de résoudre le club"}

        await _safe_report_progress(
            ctx, 1, total=3, message="Récupération bilan et matchs en parallèle…"
        )

        # Lancer bilan + last_result + next_match en parallèle
        # On passe effective_org_id au lieu de club_name pour éviter une double résolution
        bilan_coro = ffbb_bilan_service(
            club_name=None,
            organisme_id=effective_org_id,
            categorie=effective_cat or categorie,
            engagement_id=engagement_id,
            competition_id=competition_id,
            competition_type=competition_type,
            poule_id=poule_id,
            season_id=season_id,
            force_refresh=force_refresh,
        )

        if effective_org_id and categorie:
            last_coro = ffbb_last_result_service(
                organisme_id=effective_org_id,
                categorie=categorie,
                numero_equipe=resolved_num,
                engagement_id=engagement_id,
                competition_id=competition_id,
                competition_type=competition_type,
                poule_id=poule_id,
                season_id=season_id,
                force_refresh=force_refresh,
            )
            next_coro = ffbb_next_match_service(
                organisme_id=effective_org_id,
                categorie=categorie,
                numero_equipe=resolved_num,
                engagement_id=engagement_id,
                competition_id=competition_id,
                competition_type=competition_type,
                poule_id=poule_id,
                season_id=season_id,
                force_refresh=force_refresh,
            )
            raw_bilan, raw_last, raw_next = await asyncio.gather(
                bilan_coro, last_coro, next_coro, return_exceptions=True
            )
            # Normaliser les exceptions et types en dicts d'erreur / None
            bilan = (
                raw_bilan if isinstance(raw_bilan, dict) else {"error": str(raw_bilan)}
            )
            last_match = raw_last if isinstance(raw_last, dict) else None
            next_match = raw_next if isinstance(raw_next, dict) else None
        else:
            raw_bilan = await bilan_coro
            bilan = (
                raw_bilan if isinstance(raw_bilan, dict) else {"error": str(raw_bilan)}
            )
            last_match = None
            next_match = None

        await _safe_report_progress(ctx, 3, total=3, message="Résumé prêt.")
        team_data = (
            resolved_team
            or (next_match.get("team") if isinstance(next_match, dict) else None)
            or (last_match.get("team") if isinstance(last_match, dict) else None)
            or (bilan.get("team") if isinstance(bilan, dict) else None)
        )

        dynamique_data = None
        if isinstance(bilan, dict):
            eq_bilans = bilan.get("equipes_bilan")
            num_str = str(resolved_num)
            if isinstance(eq_bilans, dict) and isinstance(eq_bilans.get(num_str), dict):
                dynamique_data = eq_bilans[num_str].get("dynamique")
            if dynamique_data is None:
                dynamique_data = bilan.get("dynamique")

        # Nettoyage chirurgical des redondances (anti-verbosité) :
        # On extrait uniquement les détails propres aux matchs en évitant
        # de répéter club_resolu (3x), team (2x), _meta (3x) et status.
        def _clean_match_item(m: dict[str, Any] | None) -> dict[str, Any] | None:
            if not isinstance(m, dict):
                return None
            inner = m.get("match")
            match_data: dict[str, Any] = inner if isinstance(inner, dict) else m
            cleaned = {
                k: v
                for k, v in match_data.items()
                if k not in ("club_resolu", "team", "_meta", "status") and v is not None
            }
            return cleaned or None

        cleaned_last_match = _clean_match_item(last_match)
        cleaned_next_match = _clean_match_item(next_match)

        return {
            "team": team_data,
            "phase_courante": bilan.get("phase_courante"),
            "last_match": cleaned_last_match,
            "next_match": cleaned_next_match,
            "summary": bilan.get("bilan_total"),
            "dynamique": dynamique_data,
        }

    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 9 — Dernier résultat
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_last_result",
    title="Dernier résultat d'équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_last_result")
@zipai_surgical
async def ffbb_last_result(
    organisme_id: Annotated[
        int | str | None,
        Field(
            description="Identifiant FFBB du club (organisme_id, ex: '9326' ou 'ARA0063058')."
        ),
    ] = None,
    club_name: Annotated[
        str | None, Field(description="Nom du club (ex: 'Stade Clermontois')")
    ] = None,
    categorie: Annotated[
        str | None,
        Field(
            description="Catégorie de l'équipe précise (ex: 'U11M1', 'U11M', 'SEM1', 'NM3')."
        ),
    ] = None,
    numero_equipe: Annotated[
        int | None,
        Field(
            description="Numéro d'équipe dans la catégorie. Résoudre avec ffbb_resolve_team si ambigu."
        ),
    ] = None,
    engagement_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de l'engagement (prioritaire pour désambiguïser)."),
    ] = None,
    competition_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la compétition pour désambiguïser."),
    ] = None,
    competition_type: Annotated[
        str | None,
        Field(
            description="Type de compétition ('PLAT', 'COUPE', etc.) pour désambiguïser."
        ),
    ] = None,
    poule_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la poule pour désambiguïser."),
    ] = None,
    season_id: Annotated[
        int | str | None,
        Field(description="ID de la saison FFBB (optionnel)."),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force un rafraichissement des donnees de poule"),
    ] = False,
) -> dict[str, Any]:
    """Dernier résultat d'une équipe précise.

    SINGULIER UNIQUEMENT: retourne le dernier match joué d'une seule équipe.
    Recommendation LLM : Si la categorie est imprécise ou sans numéro (ex: 'U11M'),
    appeler d'abord `ffbb_resolve_team` pour obtenir le `numero_equipe` reel.
    """

    if not any((club_name, organisme_id, engagement_id, poule_id, competition_id)):
        return {
            "status": "error",
            "message": "Veuillez fournir un identifiant (club_name, organisme_id, engagement_id ou poule_id) pour trouver l'équipe.",
        }

    try:
        effective_refresh = force_refresh
        effective_num = numero_equipe if numero_equipe is not None else 1
        return await ffbb_last_result_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie or "",
            numero_equipe=effective_num,
            engagement_id=engagement_id,
            competition_id=competition_id,
            competition_type=competition_type,
            poule_id=poule_id,
            season_id=season_id,
            force_refresh=effective_refresh,
        )
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 10 — Prochain match
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_next_match",
    title="Prochain match d'équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_next_match")
@zipai_surgical
async def ffbb_next_match(
    organisme_id: Annotated[
        int | str | None,
        Field(
            description="Identifiant FFBB du club (organisme_id, ex: '9326' ou 'ARA0063058')."
        ),
    ] = None,
    club_name: Annotated[
        str | None, Field(description="Nom du club (ex: 'Stade Clermontois')")
    ] = None,
    categorie: Annotated[
        str | None,
        Field(
            description="Catégorie de l'équipe précise (ex: 'U11M1', 'U11M', 'SEM1', 'NM3')."
        ),
    ] = None,
    numero_equipe: Annotated[
        int | None,
        Field(
            description="Numéro d'équipe dans la catégorie. Résoudre avec ffbb_resolve_team si ambigu."
        ),
    ] = None,
    engagement_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de l'engagement (prioritaire pour désambiguïser)."),
    ] = None,
    competition_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la compétition pour désambiguïser."),
    ] = None,
    competition_type: Annotated[
        str | None,
        Field(
            description="Type de compétition ('PLAT', 'COUPE', etc.) pour désambiguïser."
        ),
    ] = None,
    poule_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la poule pour désambiguïser."),
    ] = None,
    season_id: Annotated[
        int | str | None,
        Field(description="ID de la saison FFBB (optionnel)."),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force un rafraichissement des donnees de poule"),
    ] = False,
) -> dict[str, Any]:
    """Prochain match à jouer pour une équipe précise.

    ⚠️ SINGULIER UNIQUEMENT. Si la demande est au pluriel
    ("matchs restants", "derniers matchs à jouer", "calendrier"),
    utiliser ffbb_club(action="calendrier") à la place.

    ⚠️ ATTENTION LLM : Cet outil retourne STRICTEMENT LE PROCHAIN MATCH UNIQUE.
    Ne l'utilise JAMAIS si l'utilisateur demande "les prochains matchs" au pluriel.
    Pour toute requête au pluriel, utilise OBLIGATOIREMENT `ffbb_club(action="calendrier")`
    et filtre les résultats toi-même.

    Recommendation LLM : Si la categorie est imprécise ou sans numéro (ex: 'U11M'),
    appeler d'abord `ffbb_resolve_team` pour obtenir le `numero_equipe` reel.
    """

    if not any((club_name, organisme_id, engagement_id, poule_id, competition_id)):
        return {
            "status": "error",
            "message": "Veuillez fournir un identifiant (club_name, organisme_id, engagement_id ou poule_id) pour trouver l'équipe.",
        }

    try:
        effective_num = numero_equipe if numero_equipe is not None else 1
        return await ffbb_next_match_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie or "",
            numero_equipe=effective_num,
            engagement_id=engagement_id,
            competition_id=competition_id,
            competition_type=competition_type,
            poule_id=poule_id,
            season_id=season_id,
            force_refresh=force_refresh,
        )
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 11 — Bilan de saison
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_bilan_saison",
    title="Bilan détaillé de saison",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_bilan_saison")
@zipai_surgical
async def ffbb_bilan_saison(
    organisme_id: Annotated[
        int | str | None,
        Field(description="ID FFBB du club (alternative plus rapide à club_name)."),
    ] = None,
    club_name: Annotated[
        str | None,
        Field(description="Nom du club (ex: 'Stade Clermontois', 'ASVEL')."),
    ] = None,
    categorie: Annotated[
        str | None,
        Field(
            description=(
                "Catégorie + genre + numéro d'équipe facultatif (ex: 'U11M', 'U11M1', 'U13F2', 'SeniorM'). "
                "Cette valeur sert à filtrer les engagements et les poules."
            ),
        ),
    ] = None,
    numero_equipe: Annotated[
        int | None,
        Field(
            description=(
                "Numéro d'équipe (1, 2, ...) pour identifier l'équipe précise dans la catégorie (défaut: 1)."
            )
        ),
    ] = None,
    engagement_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de l'engagement (prioritaire pour désambiguïser)."),
    ] = None,
    competition_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la compétition pour désambiguïser."),
    ] = None,
    competition_type: Annotated[
        str | None,
        Field(
            description="Type de compétition ('PLAT', 'COUPE', etc.) pour désambiguïser."
        ),
    ] = None,
    poule_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la poule pour désambiguïser."),
    ] = None,
    season_id: Annotated[
        int | str | None,
        Field(description="ID de la saison FFBB (optionnel)."),
    ] = None,
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
    l'équipe identifiée par (organisme_id/club_name, categorie, numero_equipe).

    Pour chaque phase, il retourne :
      - competition
      - poule_id
      - position
      - match_joues, gagnes, perdus, nuls
      - paniers_marques, paniers_encaissés, difference

    Et fournit également un champ `bilan_total` qui cumule toutes les phases.
    """
    try:
        await _safe_report_progress(ctx, 0, total=1, message="Calcul du bilan saison…")
        effective_refresh = force_refresh
        effective_num = numero_equipe if numero_equipe is not None else 1
        effective_cat = categorie
        if categorie:
            parsed = parse_categorie(categorie)
            if parsed.numero_equipe is not None:
                effective_num = parsed.numero_equipe

        result = await ffbb_saison_bilan_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=effective_cat,
            numero_equipe=effective_num,
            engagement_id=engagement_id,
            competition_id=competition_id,
            competition_type=competition_type,
            poule_id=poule_id,
            season_id=season_id,
            force_refresh=effective_refresh,
        )
        await _safe_report_progress(ctx, 1, total=1, message="Bilan saison prêt.")
        return result
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# TOOL 13 — Face-à-Face & Matchup Analyzer (Head-to-Head)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="ffbb_head_to_head",
    title="Face-à-Face & Comparaison d'équipes (H2H)",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_head_to_head")
@zipai_surgical
async def ffbb_head_to_head(
    club_a: Annotated[
        str | None,
        Field(description="Nom du premier club (ex: 'Stade Clermontois')."),
    ] = None,
    organisme_id_a: Annotated[
        int | str | None,
        Field(description="ID FFBB du premier club (ex: '9326')."),
    ] = None,
    club_b: Annotated[
        str | None,
        Field(description="Nom du second club / adversaire (ex: 'Vichy', 'Roanne')."),
    ] = None,
    organisme_id_b: Annotated[
        int | str | None,
        Field(description="ID FFBB du second club / adversaire."),
    ] = None,
    categorie: Annotated[
        str | None,
        Field(
            description="Catégorie d'équipe commune à comparer (ex: 'SEM1', 'U18M', 'Senior').",
        ),
    ] = None,
    engagement_id_a: Annotated[
        int | str | None,
        Field(description="ID FFBB de l'engagement équipe A (prioritaire)."),
    ] = None,
    engagement_id_b: Annotated[
        int | str | None,
        Field(description="ID FFBB de l'engagement équipe B (prioritaire)."),
    ] = None,
    engagement_id: Annotated[
        int | str | None,
        Field(
            description="ID FFBB de l'engagement partagé ou équipe A (alias pour engagement_id_a)."
        ),
    ] = None,
    competition_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la compétition pour désambiguïser."),
    ] = None,
    competition_type: Annotated[
        str | None,
        Field(
            description="Type de compétition ('PLAT', 'COUPE', etc.) pour désambiguïser."
        ),
    ] = None,
    poule_id: Annotated[
        int | str | None,
        Field(description="ID FFBB de la poule pour désambiguïser."),
    ] = None,
    season_id: Annotated[
        int | str | None,
        Field(description="ID de la saison FFBB (optionnel)."),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force le rafraîchissement des données"),
    ] = False,
    club_name: Annotated[
        str | None,
        Field(
            description="Alias pour club_a : nom du premier club (ex: 'Stade Clermontois')."
        ),
    ] = None,
    organisme_id: Annotated[
        int | str | None,
        Field(description="Alias pour organisme_id_a : ID FFBB du premier club."),
    ] = None,
    adversaire: Annotated[
        str | None,
        Field(
            description="Alias pour club_b : nom du second club / adversaire (ex: 'Vichy')."
        ),
    ] = None,
    adversaire_id: Annotated[
        int | str | None,
        Field(
            description="Alias pour organisme_id_b : ID FFBB du second club / adversaire."
        ),
    ] = None,
    ctx: Context[Any, Any, Any] | None = None,
) -> dict[str, Any]:
    """Compare deux équipes et analyse leurs confrontations directes (H2H).

    Fournit :
      - Bilan historique des confrontations directes de la saison (victoires A vs B, scores, écarts)
      - Forme récente respective de chaque équipe (V-D-V-V...) et séries en cours
      - Duel statistique des styles : Attaque vs Défense, ratio de victoires domicile/extérieur
      - Points clés narratifs prêts pour la rédaction d'articles ou de synthèses d'avant-match
    """
    try:
        await _safe_report_progress(
            ctx, 0, total=2, message="Analyse du face-à-face..."
        )
        eff_club_a = club_a or club_name
        eff_org_a = organisme_id_a or organisme_id
        eff_club_b = club_b or adversaire
        eff_org_b = organisme_id_b or adversaire_id
        eff_eng_a = engagement_id_a or engagement_id
        eff_eng_b = engagement_id_b or engagement_id

        result = await ffbb_head_to_head_service(
            club_a=eff_club_a,
            organisme_id_a=eff_org_a,
            club_b=eff_club_b,
            organisme_id_b=eff_org_b,
            categorie=categorie,
            engagement_id=engagement_id,
            engagement_id_a=eff_eng_a,
            engagement_id_b=eff_eng_b,
            competition_id=competition_id,
            competition_type=competition_type,
            poule_id=poule_id,
            season_id=season_id,
            force_refresh=force_refresh,
        )
        await _safe_report_progress(ctx, 2, total=2, message="Face-à-face prêt.")
        return result
    except Exception as e:
        raise handle_api_error(e) from e


@mcp.tool(
    name="ffbb_search_regulations",
    title="Recherche dans les règlements sportifs FFBB",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_search_regulations")
@zipai_surgical
async def ffbb_search_regulations(
    query: Annotated[
        str,
        Field(
            description=(
                "Terme ou question de recherche dans les règlements "
                "(ex: 'brûlage équipe réserve', 'défense de zone U13', 'brassages départementaux', 'barrages accession')"
            )
        ),
    ] = "",
    season: Annotated[
        str,
        Field(description="Saison sportive ciblée (par défaut '2026-2027')"),
    ] = "2026-2027",
    level: Annotated[
        Literal["federal", "regional", "departmental"] | None,
        Field(
            description=(
                "Niveau de compétition ciblé : 'federal' (FFBB national / RSG / Élite), "
                "'regional' (Ligues, ex: AURA), 'departmental' (Comités, ex: Comité 63)"
            )
        ),
    ] = None,
    organizer: Annotated[
        str | None,
        Field(
            description="Nom ou sigle de l'organisateur (ex: 'FFBB', 'Ligue AURA', 'Comité 63')"
        ),
    ] = None,
    category: Annotated[
        str | None,
        Field(
            description="Catégorie d'âge ou division (ex: 'U13', 'U15', 'U18', 'seniors', 'elite')"
        ),
    ] = None,
    topic: Annotated[
        str | None,
        Field(
            description="Mots-clés thématiques (ex: 'departages', 'brulage', 'forfaits', 'poule_haute')"
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="Nombre maximal d'extraits d'articles à retourner (défaut 5, max 10)"
        ),
    ] = 5,
    ctx: Context[Any, Any, Any] | None = None,
) -> dict[str, Any]:
    """Recherche plein texte déterministe dans les règlements officiels FFBB, régionaux et départementaux.

    Permet de retrouver les articles pertinents sur les qualifications, montées/descentes,
    brassages jeunes, règles techniques (durée, ballons, zone), forfaits et brûlage.
    """
    try:
        await _safe_report_progress(
            ctx, 1, total=2, message="Recherche dans les règlements..."
        )
        res = await search_regulations_service(
            query=query,
            season=season,
            level=level,
            organizer=organizer,
            category=category,
            topic=topic,
            limit=limit,
        )
        await _safe_report_progress(ctx, 2, total=2, message="Recherche terminée.")
        return res
    except Exception as e:
        raise handle_api_error(e) from e


@mcp.tool(
    name="ffbb_get_regulation_article",
    title="Lecture exacte d'un article de règlement FFBB",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_get_regulation_article")
@zipai_surgical
async def ffbb_get_regulation_article(
    article_number: Annotated[
        str,
        Field(
            description="Numéro ou référence de l'article (ex: 'Article 28', 'Article 51', 'Article 4.1', 'Article 7')"
        ),
    ],
    document_id: Annotated[
        str | None,
        Field(
            description=(
                "Identifiant du document source (ex: 'rsg_ffbb_2026_2027', 'rsp_u15_elite_2026_2027', "
                "'reglement_aura_2026_2027', 'reglement_comite_63_2026_2027')"
            )
        ),
    ] = None,
    organizer: Annotated[
        str | None,
        Field(
            description="Organisateur du texte (ex: 'FFBB', 'Ligue AURA', 'Comité 63')"
        ),
    ] = None,
    season: Annotated[
        str,
        Field(description="Saison sportive (défaut '2026-2027')"),
    ] = "2026-2027",
    ctx: Context[Any, Any, Any] | None = None,
) -> dict[str, Any]:
    """Récupère le texte intégral et exact d'un article spécifique de règlement sans troncature."""
    try:
        await _safe_report_progress(
            ctx, 1, total=2, message="Extraction de l'article..."
        )
        res = await get_regulation_article_service(
            document_id=document_id,
            article_number=article_number,
            organizer=organizer,
            season=season,
        )
        await _safe_report_progress(ctx, 2, total=2, message="Article extrait.")
        return res
    except Exception as e:
        raise handle_api_error(e) from e


@mcp.tool(
    name="ffbb_explain_tiebreak_rules",
    title="Règles de départage et calcul de classement FFBB",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_explain_tiebreak_rules")
@zipai_surgical
async def ffbb_explain_tiebreak_rules(
    poule_id: Annotated[
        int | None,
        Field(
            description="ID optionnel de la poule FFBB pour appliquer les règles de départage"
        ),
    ] = None,
    season: Annotated[
        str,
        Field(description="Saison sportive (défaut '2026-2027')"),
    ] = "2026-2027",
    ctx: Context[Any, Any, Any] | None = None,
) -> dict[str, Any]:
    """Fournit les règles officielles de départage en cas d'égalité (Article 28 du RSG FFBB).

    Explique le calcul du point-average particulier (confrontations directes),
    du quotient particulier, et du mini-championnat à 3 équipes ou plus.

    Utilise cet outil quand deux équipes ou plus sont à égalité de points dans une poule
    et que tu dois expliquer pourquoi l'une est classée devant l'autre.
    Avec `poule_id`, les règles sont appliquées à la poule concrète ; sans, tu obtiens
    les règles génériques. Ne pas utiliser pour obtenir le classement brut — utilise
    `ffbb_club(action="classement")` — ni pour le bilan chiffré — utilise `ffbb_bilan`.
    """
    try:
        await _safe_report_progress(
            ctx, 1, total=2, message="Chargement des règles de départage..."
        )
        res = await explain_tiebreak_rules_service(
            poule_id=poule_id,
            season=season,
        )
        await _safe_report_progress(
            ctx, 2, total=2, message="Règles de départage prêtes."
        )
        return res
    except Exception as e:
        raise handle_api_error(e) from e


@mcp.tool(
    name="ffbb_list_regulations",
    title="Liste des règlements et juridictions FFBB disponibles",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_list_regulations")
@zipai_surgical
async def ffbb_list_regulations(
    season: Annotated[
        str,
        Field(description="Saison sportive (défaut '2026-2027')"),
    ] = "2026-2027",
    ctx: Context[Any, Any, Any] | None = None,
) -> dict[str, Any]:
    """Liste l'ensemble des textes réglementaires fédéraux (RSG, RSP Élite, NM1-NM3, LF2-NF3),

    régionaux (Ligues IDF, Hauts-de-France, AURA...) et départementaux (Comités Paris, Nord, Rhône, Puy-de-Dôme...) indexés.
    """
    try:
        await _safe_report_progress(
            ctx, 1, total=2, message="Inventaire des règlements disponibles..."
        )
        res = await list_regulations_service(season=season)
        await _safe_report_progress(ctx, 2, total=2, message="Inventaire terminé.")
        return res
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------

# Injections & Optimisations de Schémas MCP
# ---------------------------------------------------------------------------


def _optimize_tool_schemas(mcp_instance: FastMCP) -> None:
    """Optimise les schémas JSON des outils MCP et élimine l'empreinte token superflue.

    1. anyOf inter-arguments : indique formellement aux agents IA qu'au moins un critère
       d'identification (organisme_id, club_name, engagement_id, poule_id, competition_id)
       est requis pour cibler l'équipe ou le club.
    2. Suppression d'output_schema : FastMCP génère des milliers de caractères de schémas
       Pydantic internes inutilisés par les clients MCP pour invoquer des outils.
    """
    tools_map = getattr(mcp_instance._tool_manager, "_tools", {})

    # Outils d'équipe acceptant organisme_id, club_name, engagement_id, poule_id ou competition_id
    team_disambiguation_tools = (
        "ffbb_resolve_team",
        "ffbb_bilan",
        "ffbb_team_summary",
        "ffbb_bilan_saison",
        "ffbb_last_result",
        "ffbb_next_match",
    )
    for tool_name in team_disambiguation_tools:
        tool = tools_map.get(tool_name)
        if tool and hasattr(tool, "parameters") and isinstance(tool.parameters, dict):
            tool.parameters["anyOf"] = [
                {"required": ["organisme_id"]},
                {"required": ["club_name"]},
                {"required": ["engagement_id"]},
                {"required": ["poule_id"]},
                {"required": ["competition_id"]},
            ]

    # ffbb_club accepte soit organisme_id, club_name, poule_id, engagement_id ou competition_id
    club_tool = tools_map.get("ffbb_club")
    if (
        club_tool
        and hasattr(club_tool, "parameters")
        and isinstance(club_tool.parameters, dict)
    ):
        club_tool.parameters["anyOf"] = [
            {"required": ["organisme_id"]},
            {"required": ["club_name"]},
            {"required": ["poule_id"]},
            {"required": ["engagement_id"]},
            {"required": ["competition_id"]},
        ]

    # ffbb_head_to_head accepte soit club_a/organisme_id_a/club_name/organisme_id/engagement_id
    h2h_tool = tools_map.get("ffbb_head_to_head")
    if (
        h2h_tool
        and hasattr(h2h_tool, "parameters")
        and isinstance(h2h_tool.parameters, dict)
    ):
        h2h_tool.parameters["anyOf"] = [
            {"required": ["club_a"]},
            {"required": ["organisme_id_a"]},
            {"required": ["club_name"]},
            {"required": ["organisme_id"]},
            {"required": ["engagement_id_a"]},
            {"required": ["engagement_id"]},
            {"required": ["poule_id"]},
        ]

    # Suppression de l'output_schema verbeux sur tous les outils pour diviser le payload tools/list
    for tool in tools_map.values():
        if hasattr(tool, "output_schema"):
            tool.output_schema = None


register_routes(mcp)
register_prompts(mcp)
register_resources(mcp)
_optimize_tool_schemas(mcp)
apply_fastmcp_json_formatting_patch()


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def main() -> None:
    # Configuration du répertoire de persistance principal (CWD)
    from pathlib import Path

    data_dir = os.environ.get(
        "FFBB_DATA_DIR", "/app/data" if os.path.exists("/app/data") else "./data"
    )
    data_path = Path(data_dir).resolve()
    try:
        data_path.mkdir(parents=True, exist_ok=True)
        os.chdir(data_path)
    except Exception as e:
        print(
            f"[warning] Impossible de changer le répertoire courant vers {data_path}: {e}"
        )

    app_log_level = _resolve_log_level(os.environ.get("FFBB_LOG_LEVEL", "INFO"))
    logging.basicConfig(
        level=app_log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    mode = os.environ.get("MCP_MODE", "stdio").lower()

    if "*" in _allowed_hosts or "*" in _allowed_origins:
        logger.warning(
            "⚠️  SÉCURITÉ : ALLOWED_HOSTS ou ALLOWED_ORIGINS est configuré sur '*' "
            "(wildcard). Toutes les origines sont acceptées. "
            "Définissez des valeurs explicites en production via les variables d'env "
            "ALLOWED_HOSTS et ALLOWED_ORIGINS."
        )

    if mode in ("sse", "http", "streamable-http"):
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "9123"))
        logger.info(
            f"Démarrage MCP FFBB en mode Streamable HTTP sur {host}:{port}/mcp ..."
        )

        mcp.settings.streamable_http_path = "/mcp"
        from ffbb_mcp.app_factory import create_app

        app = create_app(mcp, _allowed_origins)

        import uvicorn

        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=_resolve_uvicorn_log_level(app_log_level),
        )
    else:
        logger.info("Démarrage MCP FFBB en mode stdio...")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
