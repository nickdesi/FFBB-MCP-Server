"""Package d'enregistrement modulaire des outils FastMCP FFBB.

Divise le fichier monolithique server.py en sous-modules thématiques.
"""

from .club import ffbb_club, ffbb_head_to_head, register_club_tools
from .common import (
    _READONLY_ANNOTATIONS,
    _get_server_service,
    handle_api_error,
    track_tool_usage,
)
from .regulations import (
    ffbb_explain_tiebreak_rules,
    ffbb_get_regulation_article,
    ffbb_list_regulations,
    ffbb_search_regulations,
    register_regulations_tools,
)
from .system import (
    ffbb_get,
    ffbb_get_lives,
    ffbb_get_saisons,
    ffbb_lives,
    ffbb_saisons,
    ffbb_search,
    ffbb_version,
    register_system_tools,
)
from .team import (
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

__all__ = [
    "_READONLY_ANNOTATIONS",
    "_accepted_match_envelope",
    "_get_server_service",
    "_require_club_identifier",
    "ffbb_bilan",
    "ffbb_bilan_saison",
    "ffbb_club",
    "ffbb_explain_tiebreak_rules",
    "ffbb_find_team_candidates",
    "ffbb_get",
    "ffbb_get_lives",
    "ffbb_get_regulation_article",
    "ffbb_get_saisons",
    "ffbb_head_to_head",
    "ffbb_last_result",
    "ffbb_list_regulations",
    "ffbb_lives",
    "ffbb_next_match",
    "ffbb_resolve_team",
    "ffbb_saisons",
    "ffbb_search",
    "ffbb_search_regulations",
    "ffbb_team_summary",
    "ffbb_version",
    "handle_api_error",
    "register_club_tools",
    "register_regulations_tools",
    "register_system_tools",
    "register_team_tools",
    "track_tool_usage",
]
