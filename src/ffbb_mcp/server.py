# Note mypy: les `# type: ignore[untyped-decorator]` sur les outils
# dans ce projet proviennent du décorateur FastMCP dont les stubs
# officiels ne sont pas typés. Convention documentée au niveau du projet.

from __future__ import annotations

import logging
import os
import urllib.parse

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool

# Alias de compatibilité pour accès legacy camelCase sur les objets Tool
if not hasattr(Tool, "inputSchema"):
    Tool.inputSchema = property(lambda self: self.input_schema)  # type: ignore[attr-defined]
if not hasattr(Tool, "outputSchema"):
    Tool.outputSchema = property(lambda self: self.output_schema)  # type: ignore[attr-defined]

from . import __version__ as _PACKAGE_VERSION
from .models import CalendrierMatch
from .prompts import ROUTING_PROMPT, register_prompts
from .resources import register_resources
from .routes import register_routes
from .services import (
    explain_tiebreak_rules_service,
    ffbb_bilan_service,
    ffbb_equipes_club_service,
    ffbb_find_team_candidates_service,
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
    get_engagement_service,
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
from .tools.club import (
    ffbb_club,
    ffbb_head_to_head,
    register_club_tools,
)
from .tools.common import (
    _READONLY_ANNOTATIONS,
    _safe_report_progress,
    track_tool_usage,
)
from .tools.regulations import (
    ffbb_explain_tiebreak_rules,
    ffbb_get_regulation_article,
    ffbb_list_regulations,
    ffbb_search_regulations,
    register_regulations_tools,
)
from .tools.system import (
    _sdk_version,
    _validate_filter_by,
    ffbb_get,
    ffbb_get_lives,
    ffbb_get_saisons,
    ffbb_lives,
    ffbb_saisons,
    ffbb_search,
    ffbb_version,
    register_system_tools,
)
from .tools.team import (
    _accepted_match_envelope,
    _require_club_identifier,
    ffbb_bilan,
    ffbb_bilan_saison,
    ffbb_find_team_candidates,
    ffbb_last_result,
    ffbb_next_match,
    ffbb_resolve_team,
    ffbb_team_summary,
    register_team_tools,
)

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
# Initialisation FastMCP & Sécurité Transport
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

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=_dns_protection,
    allowed_hosts=_allowed_hosts,
    allowed_origins=_allowed_origins,
)

mcp: MCPServer = MCPServer(
    "FFBB MCP Server",
    instructions=(
        ROUTING_PROMPT
        + "\n[Données live. Tableau classement: | Rang | **Nom Équipe** 🎯 | PTS | J | G | P | M | E | Diff | avec cible en GRAS (is_target=True). Pas de recalcul.]"
    ),
    dependencies=["mcp", "ffbb-data-client"],
)


# ---------------------------------------------------------------------------
# Enregistrement modulaire des outils FastMCP
# ---------------------------------------------------------------------------

register_system_tools(mcp)
register_club_tools(mcp)
register_team_tools(mcp)
register_regulations_tools(mcp)


# ---------------------------------------------------------------------------
# Injections & Optimisations de Schémas MCP
# ---------------------------------------------------------------------------


def _optimize_tool_schemas(mcp_instance: MCPServer) -> None:
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

    # ffbb_head_to_head accepte soit club_a/organisme_id_a/club_name/organisme_id/engagement_id/engagement_id_a/engagement_id_b
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
            {"required": ["engagement_id_b"]},
            {"required": ["engagement_id"]},
            {"required": ["poule_id"]},
        ]

    # ffbb_find_team_candidates accepte soit organisme_id soit club_name
    cand_tool = tools_map.get("ffbb_find_team_candidates")
    if (
        cand_tool
        and hasattr(cand_tool, "parameters")
        and isinstance(cand_tool.parameters, dict)
    ):
        cand_tool.parameters["anyOf"] = [
            {"required": ["organisme_id"]},
            {"required": ["club_name"]},
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

        from ffbb_mcp.app_factory import create_app

        app = create_app(
            mcp,
            allowed_origins=_allowed_origins,
            transport_security=transport_security,
        )

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


__all__ = [
    "_PACKAGE_VERSION",
    "_READONLY_ANNOTATIONS",
    "CalendrierMatch",
    "_accepted_match_envelope",
    "_optimize_tool_schemas",
    "_require_club_identifier",
    "_resolve_log_level",
    "_resolve_uvicorn_log_level",
    "_safe_report_progress",
    "_sdk_version",
    "_validate_filter_by",
    "explain_tiebreak_rules_service",
    "ffbb_bilan",
    "ffbb_bilan_saison",
    "ffbb_bilan_service",
    "ffbb_club",
    "ffbb_equipes_club_service",
    "ffbb_explain_tiebreak_rules",
    "ffbb_find_team_candidates",
    "ffbb_find_team_candidates_service",
    "ffbb_get",
    "ffbb_get_classement_service",
    "ffbb_get_lives",
    "ffbb_get_regulation_article",
    "ffbb_get_saisons",
    "ffbb_head_to_head",
    "ffbb_head_to_head_service",
    "ffbb_last_result",
    "ffbb_last_result_service",
    "ffbb_list_regulations",
    "ffbb_lives",
    "ffbb_next_match",
    "ffbb_next_match_service",
    "ffbb_resolve_team",
    "ffbb_resolve_team_service",
    "ffbb_saison_bilan_service",
    "ffbb_saisons",
    "ffbb_search",
    "ffbb_search_regulations",
    "ffbb_search_service",
    "ffbb_team_summary",
    "ffbb_version",
    "find_team_poule_service",
    "format_poule_response",
    "get_cache_ttls",
    "get_calendrier_club_service",
    "get_competition_service",
    "get_engagement_service",
    "get_entraineur_service",
    "get_lives_service",
    "get_officiel_service",
    "get_organisme_service",
    "get_poule_service",
    "get_regulation_article_service",
    "get_rencontre_service",
    "get_saisons_service",
    "get_salle_service",
    "handle_api_error",
    "list_regulations_service",
    "main",
    "mcp",
    "register_club_tools",
    "register_regulations_tools",
    "register_system_tools",
    "register_team_tools",
    "resolve_club_and_org",
    "resolve_poule_id_service",
    "search_regulations_service",
    "track_tool_usage",
    "transport_security",
]


if __name__ == "__main__":
    main()
