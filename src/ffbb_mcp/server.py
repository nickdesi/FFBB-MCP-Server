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

from ffbb_mcp.models import BilanResponse, CalendrierMatch  # noqa: TC001

from . import __version__ as _PACKAGE_VERSION
from .metrics import record_tool_call
from .prompts import ROUTING_PROMPT, register_prompts
from .resources import register_resources
from .routes import register_routes
from .services import (
    ffbb_bilan_service,
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    ffbb_last_result_service,
    ffbb_next_match_service,
    ffbb_resolve_team_service,
    ffbb_saison_bilan_service,
    ffbb_search_service,
    format_poule_response,
    get_cache_ttls,
    get_calendrier_club_service,
    get_competition_service,
    get_entraineur_service,
    get_lives_service,
    get_officiel_service,
    get_organisme_service,
    get_poule_service,
    get_rencontre_service,
    get_saisons_service,
    handle_api_error,
    resolve_poule_id_service,
    search_organismes_service,
)
from .utils import prune_payload


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

_allowed_hosts_raw = os.environ.get("ALLOWED_HOSTS", "*")
_allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "*")
_allowed_hosts = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]
_allowed_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]

_public_url = os.environ.get("PUBLIC_URL", "https://ffbb.desimone.fr").strip()
try:
    _parsed_url = urllib.parse.urlparse(_public_url)
    _public_host = _parsed_url.hostname
except Exception:
    _public_host = "ffbb.desimone.fr"

# Ajout automatique de l'hôte public par défaut
if _public_host and _public_host not in _allowed_hosts and "*" not in _allowed_hosts:
    _allowed_hosts.append(_public_host)

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
        ROUTING_PROMPT + "\n\n" + "Données FFBB (basketball français). "
        ""
        "[ZIPAI DIRECTIVE: Output technical data only. No filler, no echo, no meta.]\n"
        "## RÈGLE ABSOLUE — CLASSEMENT POULE\n"
        "Suivre strictement le format de tableau et les colonnes définis dans le prompt expert `expert_basket` (Rang, Équipe, PTS, J, G, P, M, E, Diff). "
        "Interdiction de recalculer les points ou la différence.\n\n"
        "## Règle : Matchs restants d'une équipe\n"
        "Pour répondre à 'combien de matchs restent-il à [équipe] ?', NE PAS se contenter de ffbb_get(type='poule') "
        "car les données peuvent être tronquées (_omitted_count > 0).\n"
        "Workflow obligatoire :\n"
        "1. ffbb_team_summary → identifier poule_id, dernière journée jouée.\n"
        "2. ffbb_club(action='calendrier', filtre='<categorie>') → calendrier complet du club, "
        "puis filtrer les rencontres non jouées."
    ),
    dependencies=["mcp", "ffbb-data-client"],
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
        Field(description="Nombre maximum de résultats à retourner."),
    ] = 20,
    filter_by: Annotated[
        str | None,
        Field(description="Filtre Meilisearch natif (ex: 'codePostal = \"63000\"')."),
    ] = None,
    sort: Annotated[
        list[str] | None,
        Field(description="Tri Meilisearch (ex: ['libelle:asc'])."),
    ] = None,
) -> list[dict[str, Any]]:
    """Recherche FFBB — clubs, compétitions, matchs, salles, tournois, etc.

    type='all' → recherche globale (meilleur point d'entrée).
    type='organismes' → clubs uniquement.
    type='competitions' → compétitions uniquement.
    Résultats contiennent un 'id' à utiliser avec ffbb_get ou ffbb_club.
    """
    try:
        safe_filter = _validate_filter_by(filter_by)
        # Délègue la logique détaillée au service dédié pour centraliser le dispatch
        return await ffbb_search_service(
            query=query, type=type, limit=limit, filter_by=safe_filter, sort=sort
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
            description=(
                "Catégorie + genre + numéro d'équipe (ex: 'U11M1', 'U13F2', 'U15M', 'Senior')."
            ),
        ),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(
            description="Si True, contourne le cache pour récupérer des données fraîches."
        ),
    ] = False,
    ctx: Context[Any, Any, Any] | None = None,
) -> dict[str, Any] | BilanResponse:
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
        effective_refresh = force_refresh
        result = await ffbb_bilan_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
            force_refresh=effective_refresh,
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
@track_tool_usage("ffbb_get")
@zipai_surgical
async def ffbb_get(
    id: Annotated[
        int,
        Field(
            description=(
                "Identifiant numérique FFBB exact. Ne pas passer un nom de club: "
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
            description=(
                "Action club. Utiliser 'calendrier' pour les demandes au pluriel "
                "(matchs restants, calendrier, prochaines journées)."
            )
        ),
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
        int | str | None,
        Field(
            description=(
                "Identifiant FFBB du club (ex: 1234 ou 'ARA0063058'). Si absent, `club_name` est utilise pour "
                "effectuer une recherche."
            )
        ),
    ] = None,
    filtre: Annotated[
        str | None,
        Field(
            description=(
                "Filtre facultatif de categorie/genre (ex: 'U11', 'U11M', 'U11F'). "
                "Pour une équipe précise, compléter avec numero_equipe."
            )
        ),
    ] = None,
    adversaire: Annotated[
        str | None,
        Field(
            description=(
                "Nom de l'équipe adversaire pour filtrer uniquement les confrontations directes "
                "(ex: 'Royat Orcines', 'Stade Clermontois'). "
                "Utilisé avec action='calendrier'. Insensible à la casse et aux accents."
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
    date_debut: Annotated[
        str | None,
        Field(
            description="Date de début de filtrage au format YYYY-MM-DD (ex: '2026-05-01')."
        ),
    ] = None,
    date_fin: Annotated[
        str | None,
        Field(
            description="Date de fin de filtrage au format YYYY-MM-DD (ex: '2026-05-31')."
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Field(
            description="Nombre maximum de matchs de calendrier à retourner (pagination/limite)."
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
) -> list[dict[str, Any]] | list[CalendrierMatch]:
    """Outils agreges autour d'un club (calendrier, equipes, classement).

    ✅ Outil de référence pour toute demande au pluriel :
    "matchs restants", "derniers matchs à jouer", "prochaines journées",
    "calendrier de fin de saison".

    ⚡ `action="calendrier"` est l'outil le plus fiable pour obtenir TOUTES les rencontres
    passées et futures d'une équipe/catégorie, sans les limitations de `ffbb_get(poule)`.

    🎯 Pour isoler les confrontations directes entre deux équipes :
    Utilise le paramètre `adversaire` avec `action="calendrier"`.
    Exemple : confrontations Royat vs Pont-du-Château en phase 3
    → ffbb_club(action="calendrier", club_name="Pont du Chateau", filtre="U11M",
                adversaire="Royat Orcines", numero_equipe=1)

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
            effective_refresh = force_refresh
            kwargs: dict[str, Any] = {
                "club_name": club_name,
                "organisme_id": target_org_id,
                "categorie": filtre,
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
            return await get_calendrier_club_service(**kwargs)
        elif action == "equipes":
            if not target_org_id:
                return [
                    {
                        "error": "organisme_id requis pour l'action 'equipes' (la résolution du club_name a échoué)."
                    }
                ]
            result = await ffbb_equipes_club_service(
                organisme_id=target_org_id, filtre=filtre
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
@track_tool_usage("ffbb_lives")
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
@track_tool_usage("ffbb_saisons")
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
    title="Résolution d'équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_resolve_team")
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
        str | None,
        Field(
            description=(
                "Catégorie + genre + numéro d'équipe (ex: 'U11M1', 'U13F2', 'U15M'). "
                "Si le numéro manque, cet outil retourne la bonne équipe ou des candidats."
            ),
        ),
    ] = None,
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
    title="Résumé complet d'équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_team_summary")
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

    Recommandé pour une vue rapide d'une équipe précise. Si la catégorie est ambiguë
    ou sans numéro d'équipe, l'outil tente une résolution via `ffbb_resolve_team`.
    Pour une liste de matchs restants, utiliser plutôt `ffbb_club(action="calendrier")`.
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
            except (TypeError, ValueError):  # fmt: skip
                resolved_num = 1

        # last_result et next_match nécessitent organisme_id
        effective_org_id = resolved_org_id

        if not effective_org_id:
            return {"error": "Impossible de résoudre le club"}

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
                organisme_id=effective_org_id,
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
    title="Dernier résultat d'équipe",
    annotations=_READONLY_ANNOTATIONS,
)
@track_tool_usage("ffbb_last_result")
@zipai_surgical
async def ffbb_last_result(
    categorie: Annotated[
        str,
        Field(
            description="Catégorie de l'équipe précise (ex: 'U11M1', 'U11M', 'U11F')"
        ),
    ],
    club_name: Annotated[
        str | None, Field(description="Nom du club (ex: 'Stade Clermontois')")
    ] = None,
    organisme_id: Annotated[
        int | str | None,
        Field(
            description="Identifiant FFBB du club (organisme_id, ex: 1234 ou 'ARA0063058')"
        ),
    ] = None,
    numero_equipe: Annotated[
        int,
        Field(
            description="Numéro d'équipe dans la catégorie. Résoudre avec ffbb_resolve_team si ambigu."
        ),
    ] = 1,
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

    if club_name is None and organisme_id is None:
        return {
            "status": "error",
            "message": "Veuillez fournir club_name ou organisme_id pour trouver l'équipe.",
        }

    try:
        effective_refresh = force_refresh
        return await ffbb_last_result_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
            numero_equipe=numero_equipe,
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
    categorie: Annotated[
        str,
        Field(
            description="Catégorie de l'équipe précise (ex: 'U11M1', 'U11M', 'U11F')"
        ),
    ],
    club_name: Annotated[
        str | None, Field(description="Nom du club (ex: 'Stade Clermontois')")
    ] = None,
    organisme_id: Annotated[
        int | str | None,
        Field(
            description="Identifiant FFBB du club (organisme_id, ex: 1234 ou 'ARA0063058')"
        ),
    ] = None,
    numero_equipe: Annotated[
        int,
        Field(
            description="Numéro d'équipe dans la catégorie. Résoudre avec ffbb_resolve_team si ambigu."
        ),
    ] = 1,
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

    if club_name is None and organisme_id is None:
        return {
            "status": "error",
            "message": "Veuillez fournir club_name ou organisme_id pour trouver l'équipe.",
        }

    try:
        return await ffbb_next_match_service(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
            numero_equipe=numero_equipe,
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
        effective_refresh = force_refresh
        result = await ffbb_saison_bilan_service(
            organisme_id=organisme_id,
            categorie=categorie,
            numero_equipe=numero_equipe,
            force_refresh=effective_refresh,
        )
        if ctx:
            await ctx.report_progress(1, total=1, message="Bilan saison prêt.")
        return result
    except Exception as e:
        raise handle_api_error(e) from e


# ---------------------------------------------------------------------------
# Injections
# ---------------------------------------------------------------------------

register_routes(mcp)
register_prompts(mcp)
register_resources(mcp)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def main() -> None:
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
