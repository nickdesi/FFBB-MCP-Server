"""Outils MCP FastMCP généraux : version, recherche globale, inspection, lives et saisons."""

from __future__ import annotations

import os
import platform
import re
from importlib.metadata import PackageNotFoundError as _PkgNotFound
from importlib.metadata import version as _meta_version
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

if TYPE_CHECKING:
    from mcp.server import MCPServer

from ffbb_mcp import __version__ as _PACKAGE_VERSION
from ffbb_mcp.presentation import format_source_label
from ffbb_mcp.services import (
    ffbb_search_service,
    find_team_poule_service,
    format_poule_response,
    get_cache_ttls,
    get_competition_service,
    get_engagement_service,
    get_entraineur_service,
    get_lives_service,
    get_officiel_service,
    get_organisme_service,
    get_poule_service,
    get_rencontre_service,
    get_saisons_service,
    get_salle_service,
)
from ffbb_mcp.utils import format_team_name

from .common import (
    _READONLY_ANNOTATIONS,
    _get_server_service,
    handle_api_error,
    track_tool_usage,
)

_FILTER_BY_MAX_LEN = 500
_FILTER_BY_BLOCKED = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


def _validate_filter_by(filter_by: str | None) -> str | None:
    """Valide une expression de filtrage Meilisearch."""
    if filter_by is None:
        return None
    if len(filter_by) > _FILTER_BY_MAX_LEN:
        raise ValueError(
            f"filter_by dépasse la longueur maximale ({_FILTER_BY_MAX_LEN} caractères)"
        )
    if _FILTER_BY_BLOCKED.search(filter_by):
        raise ValueError("filter_by contient des caractères de contrôle invalides")
    return filter_by


def _sdk_version(package: str) -> str:
    """Retourne la version installée d'un package Python."""
    try:
        return _meta_version(package)
    except _PkgNotFound:
        return "unknown"


def _build_default_get_presentation(
    type_name: str, resource_id: int | str, data: dict[str, Any]
) -> dict[str, Any]:
    """Construit un bloc de présentation par défaut pour ffbb_get."""
    if type_name == "competition":
        nom = (
            data.get("nom")
            or data.get("competition_nom")
            or f"Compétition {resource_id}"
        )
        poule_nom = data.get("poule_nom")
        club_nom = data.get("club")
        if data.get("status") == "found" and poule_nom:
            short_ans = f"Compétition '{nom}' : poule '{poule_nom}' résolue pour {club_nom or 'le club'}."
            detail = f"Poule: {poule_nom} (ID: {data.get('poule_id')}) · Club: {club_nom or 'Non précisé'}."
        else:
            poules = data.get("poules") or []
            short_ans = f"Compétition '{nom}' ({len(poules)} poule(s))."
            code = data.get("code") or ""
            raw_saison = data.get("saison")
            saison_lbl = (
                raw_saison.get("libelle")
                if isinstance(raw_saison, dict)
                else (str(raw_saison) if raw_saison else "")
            )
            detail = (
                f"Code: {code} · Saison: {saison_lbl}."
                if code or saison_lbl
                else "Détails de la compétition."
            )
    elif type_name == "organisme":
        nom = data.get("nom") or f"Organisme {resource_id}"
        code = data.get("code") or ""
        short_ans = (
            f"Club / Organisme : {nom} ({code})."
            if code
            else f"Club / Organisme : {nom}."
        )
        raw_commune = data.get("commune")
        commune = (
            raw_commune.get("libelle")
            if isinstance(raw_commune, dict)
            else (str(raw_commune) if raw_commune else "")
        )
        detail = f"Ville : {commune}." if commune else "Détails de l'organisme."
    elif type_name == "engagement":
        raw_team = data.get("team")
        team: dict[str, Any] = raw_team if isinstance(raw_team, dict) else {}
        raw_club = data.get("club")
        club: dict[str, Any] = raw_club if isinstance(raw_club, dict) else {}
        raw_classement = data.get("classement")
        classement: dict[str, Any] = (
            raw_classement if isinstance(raw_classement, dict) else {}
        )
        raw_poule = data.get("poule")
        poule: dict[str, Any] = raw_poule if isinstance(raw_poule, dict) else {}

        raw_classement_eng = classement.get("id_engagement")
        classement_nom = (
            raw_classement_eng.get("nom")
            if isinstance(raw_classement_eng, dict)
            else ""
        )
        club_nom = (
            team.get("nom_equipe")
            or club.get("nom")
            or classement_nom
            or data.get("nom")
            or ""
        )
        team_label = team.get("team_label") or ""
        num_eq = data.get("numero_equipe") or team.get("numero_equipe")
        label_equipe = (
            format_team_name(club_nom, num_eq)
            if club_nom
            else f"Engagement {resource_id}"
        )
        if team_label and team_label not in label_equipe:
            label_equipe = f"{label_equipe} ({team_label})"

        raw_competition = data.get("competition")
        competition: dict[str, Any] = (
            raw_competition if isinstance(raw_competition, dict) else {}
        )
        nom_comp = competition.get("nom") or ""
        short_ans = (
            f"Engagement : {label_equipe} ({nom_comp})."
            if nom_comp
            else f"Engagement : {label_equipe}."
        )
        nom_poule = poule.get("nom") or ""
        cal = data.get("calendrier")
        matchs_cnt = len(cal) if isinstance(cal, list) else 0
        detail = (
            f"Poule : {nom_poule} · {matchs_cnt} match(s) au calendrier."
            if nom_poule
            else f"{matchs_cnt} match(s) au calendrier."
        )
    elif type_name == "poule":
        nom = data.get("nom") or f"Poule {resource_id}"
        cls = data.get("classements") or []
        rcts = data.get("rencontres") or []
        short_ans = f"Poule '{nom}' ({len(cls)} équipe(s), {len(rcts)} rencontre(s))."
        detail = "Détails complets de la poule."
    elif type_name == "rencontre":
        eq1 = data.get("nomEquipe1") or data.get("equipe1") or "Équipe 1"
        eq2 = data.get("nomEquipe2") or data.get("equipe2") or "Équipe 2"
        sc1 = data.get("scoreEquipe1")
        sc2 = data.get("scoreEquipe2")
        score_str = f" : {sc1} - {sc2}" if sc1 is not None and sc2 is not None else ""
        short_ans = f"Match {eq1} vs {eq2}{score_str}."
        date_str = data.get("date_rencontre") or data.get("date") or ""
        detail = f"Date : {date_str}." if date_str else "Détails de la rencontre."
    elif type_name == "salle":
        nom = data.get("nom") or f"Salle {resource_id}"
        ville = data.get("ville") or ""
        short_ans = f"Salle : {nom}."
        detail = f"Localisation : {ville}." if ville else "Détails de la salle."
    else:
        short_ans = f"Ressource {type_name} {resource_id}."
        detail = "Données chargées depuis la FFBB."

    return {
        "short_answer": short_ans,
        "detail_line": detail,
        "source_label": format_source_label(),
        "warnings": [],
    }


@track_tool_usage("ffbb_version")
async def ffbb_version() -> dict[str, Any]:
    """Informations de version et configuration runtime du serveur FFBB MCP.

    Retourne `dict` compact et typé `{package_version, mcp_sdk_version,
    python_version, transport, cache_ttls}` ; lecture seule, idempotent, sans
    appel réseau externe ni effet de bord, <10ms.
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


@track_tool_usage("ffbb_search")
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
            "news",
            "galeries",
            "rss",
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
        Field(description="Tri Meilisearch (ex: ['nom:asc'])."),
    ] = None,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force le rafraîchissement des données."),
    ] = False,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Recherche FFBB — clubs, compétitions, matchs, salles, tournois, news, actualités, etc."""
    svc = _get_server_service("ffbb_search_service", ffbb_search_service)
    try:
        safe_filter = _validate_filter_by(filter_by)
        return await svc(
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


@track_tool_usage("ffbb_get")
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
            "engagement",
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
    """Recupere une ressource FFBB par identifiant."""
    find_poule_svc = _get_server_service(
        "find_team_poule_service", find_team_poule_service
    )
    get_comp_svc = _get_server_service(
        "get_competition_service", get_competition_service
    )
    get_poule_svc = _get_server_service("get_poule_service", get_poule_service)
    format_poule_svc = _get_server_service(
        "format_poule_response", format_poule_response
    )
    get_org_svc = _get_server_service("get_organisme_service", get_organisme_service)
    get_eng_svc = _get_server_service("get_engagement_service", get_engagement_service)
    get_rencontre_svc = _get_server_service(
        "get_rencontre_service", get_rencontre_service
    )
    get_officiel_svc = _get_server_service("get_officiel_service", get_officiel_service)
    get_entraineur_svc = _get_server_service(
        "get_entraineur_service", get_entraineur_service
    )
    get_salle_svc = _get_server_service("get_salle_service", get_salle_service)

    try:
        if type == "competition":
            if club:
                res = await find_poule_svc(competition_id=id, organisme_id_or_name=club)
            else:
                res = await get_comp_svc(competition_id=id)
        elif type == "poule":
            poule_data = await get_poule_svc(id, force_refresh=force_refresh)
            res = await format_poule_svc(poule_data)
        elif type == "organisme":
            res = await get_org_svc(organisme_id=id)
        elif type == "engagement":
            res = await get_eng_svc(id, force_refresh=force_refresh)
        elif type == "rencontre":
            res = await get_rencontre_svc(id)
        elif type == "officiel":
            res = await get_officiel_svc(id)
        elif type == "entraineur":
            res = await get_entraineur_svc(id)
        elif type == "salle":
            res = await get_salle_svc(id)
        else:
            return {"error": f"Type inconnu: {type}"}

        if isinstance(res, dict) and "presentation" not in res:
            res["presentation"] = _build_default_get_presentation(type, id, res)
        return res
    except Exception as e:
        raise handle_api_error(e) from e


@track_tool_usage("ffbb_lives")
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
    organisme_id: Annotated[
        int | str | None,
        Field(description="ID du club pour cibler et compléter le flux live."),
    ] = None,
    club_name: Annotated[
        str | None,
        Field(description="Nom du club si son identifiant n'est pas connu."),
    ] = None,
    categorie: Annotated[
        str | None,
        Field(description="Catégorie de l'équipe ciblée, par exemple U18M ou NM2."),
    ] = None,
    numero_equipe: Annotated[
        int | None,
        Field(description="Numéro de l'équipe ciblée dans la catégorie."),
    ] = None,
    engagement_id: Annotated[
        int | str | None,
        Field(description="ID d'engagement précis de l'équipe ciblée."),
    ] = None,
    include_calendar_fallback: Annotated[
        bool,
        Field(
            description=(
                "Pour une cible club/équipe, complète le flux FFBB avec les matchs "
                "dont l'horaire est dépassé, sans les présenter comme live confirmés."
            )
        ),
    ] = True,
) -> list[dict[str, Any]]:
    """Flux live FFBB, éventuellement complété par un calendrier ciblé et prudent."""
    svc = _get_server_service("get_lives_service", get_lives_service)
    try:
        filters = {
            "organisme_id": organisme_id,
            "club_name": club_name,
            "categorie": categorie,
            "numero_equipe": numero_equipe,
            "engagement_id": engagement_id,
        }
        if not any(value is not None for value in filters.values()):
            return await svc(include_scheduled=include_scheduled)
        return await svc(
            include_scheduled=include_scheduled,
            organisme_id=organisme_id,
            club_name=club_name,
            categorie=categorie,
            numero_equipe=numero_equipe,
            engagement_id=engagement_id,
            include_calendar_fallback=include_calendar_fallback,
        )
    except Exception as e:
        raise handle_api_error(e) from e


# Alias direct pour compatibilité des imports
ffbb_lives = ffbb_get_lives


@track_tool_usage("ffbb_saisons")
async def ffbb_get_saisons(
    active_only: Annotated[
        bool, Field(description="True = saison active uniquement.")
    ] = False,
    force_refresh: Annotated[
        bool, Field(description="Si True, contourne le cache.")
    ] = False,
) -> list[dict[str, Any]]:
    """Liste des saisons FFBB (référentiel temporel)."""
    svc = _get_server_service("get_saisons_service", get_saisons_service)
    try:
        return await svc(active_only=active_only, force_refresh=force_refresh)
    except Exception as e:
        raise handle_api_error(e) from e


# Alias direct pour compatibilité des imports
ffbb_saisons = ffbb_get_saisons


def register_system_tools(mcp: MCPServer) -> None:
    """Enregistre les outils système et de recherche auprès du serveur FastMCP."""
    mcp.add_tool(
        ffbb_version,
        name="ffbb_version",
        title="Version et diagnostics serveur",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_search,
        name="ffbb_search",
        title="Recherche FFBB (multi-index)",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_get,
        name="ffbb_get",
        title="Ressource FFBB par identifiant",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_get_lives,
        name="ffbb_lives",
        title="Scores en direct",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_get_saisons,
        name="ffbb_saisons",
        title="Liste des saisons FFBB",
        annotations=_READONLY_ANNOTATIONS,
    )
