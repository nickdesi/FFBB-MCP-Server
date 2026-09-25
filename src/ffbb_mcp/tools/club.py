"""Outils FastMCP pour les clubs : calendrier agrégé, équipes, classement et face-à-face (H2H)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import Context  # noqa: TC002
from pydantic import Field

from ffbb_mcp.models import CalendrierMatch  # noqa: TC001

if TYPE_CHECKING:
    from mcp.server import MCPServer
from ffbb_mcp.services import (
    ffbb_equipes_club_service,
    ffbb_get_classement_service,
    ffbb_head_to_head_service,
    get_calendrier_club_service,
    resolve_club_and_org,
    resolve_poule_id_service,
)
from ffbb_mcp.services.common import (
    disambiguate_clubs_by_category,
    get_primary_club,
    is_real_ambiguity,
)
from ffbb_mcp.services.division import _parse_division_code
from ffbb_mcp.utils import parse_categorie

from .common import (
    _READONLY_ANNOTATIONS,
    _get_server_service,
    _safe_report_progress,
    handle_api_error,
    track_tool_usage,
)

logger = logging.getLogger("ffbb-mcp")


@track_tool_usage("ffbb_club")
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
    scope: Annotated[
        Literal["team", "club", "competition"] | None,
        Field(
            description="Scope : 'team' (équipe résolue), 'club' (global club) ou 'competition'."
        ),
    ] = None,
    include_competition_types: Annotated[
        list[str] | None,
        Field(description="Types de compétition inclus (ex: ['DIV'])."),
    ] = None,
    exclude_competition_types: Annotated[
        list[str] | None,
        Field(description="Types de compétition exclus (ex: ['PLAT'])."),
    ] = None,
    include_friendlies: Annotated[
        bool,
        Field(description="Inclut les amicaux (exclus par défaut)."),
    ] = False,
    include_youth: Annotated[
        bool,
        Field(description="Inclut les équipes jeunes si demande senior."),
    ] = False,
    include_reserves: Annotated[
        bool,
        Field(description="Inclut les réserves si demande équipe 1."),
    ] = False,
    status_filter: Annotated[
        list[str] | None,
        Field(description="Filtre statuts : scheduled, live, final."),
    ] = None,
    strict_filters: Annotated[
        bool,
        Field(description="Filtrage strict sans extrapolation (défaut True)."),
    ] = True,
    group_by: Annotated[
        Literal["competition", "team", "date"] | None,
        Field(description="Regroupement : competition, team ou date."),
    ] = None,
) -> list[dict[str, Any]] | list[CalendrierMatch] | dict[str, Any]:
    """Outils agrégés club : calendrier (matchs pluriels), équipes engagées ou classement."""
    cal_svc = _get_server_service(
        "get_calendrier_club_service", get_calendrier_club_service
    )
    resolve_club_svc = _get_server_service("resolve_club_and_org", resolve_club_and_org)
    equipes_svc = _get_server_service(
        "ffbb_equipes_club_service", ffbb_equipes_club_service
    )
    resolve_pid_svc = _get_server_service(
        "resolve_poule_id_service", resolve_poule_id_service
    )
    classement_svc = _get_server_service(
        "ffbb_get_classement_service", ffbb_get_classement_service
    )

    try:
        effective_filtre = filtre or categorie

        # Action calendrier : le service gère résolution + ambiguïté en interne
        if action == "calendrier":
            if not organisme_id and not club_name and engagement_id is not None:
                try:
                    from ffbb_mcp.client import FFBBClientFactory

                    _eng_client = await FFBBClientFactory.get_client_async()
                    _eng_data = await _eng_client.get_engagement_async(
                        str(engagement_id).strip()
                    )
                    if _eng_data is not None and getattr(
                        _eng_data, "idOrganisme", None
                    ):
                        organisme_id = str(_eng_data.idOrganisme)
                except Exception:
                    logger.debug(
                        "Résolution organisme depuis engagement_id échouée",
                        exc_info=True,
                    )
            if not organisme_id and not club_name:
                return {
                    "status": "error",
                    "message": "Fournir organisme_id ou club_name (ou un engagement_id résolvable)",
                    "items": [],
                    "_meta": {
                        "total": 0,
                        "returned": 0,
                        "limit": limit or 0,
                        "offset": offset or 0,
                        "has_more": False,
                        "sort": "scheduled_at:asc",
                    },
                }
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
            if poule_id is not None:
                kwargs["poule_id"] = poule_id
            if season_id is not None:
                kwargs["season_id"] = season_id
            if scope is not None:
                kwargs["scope"] = scope
            if include_competition_types is not None:
                kwargs["include_competition_types"] = include_competition_types
            if exclude_competition_types is not None:
                kwargs["exclude_competition_types"] = exclude_competition_types
            if include_friendlies:
                kwargs["include_friendlies"] = include_friendlies
            if include_youth:
                kwargs["include_youth"] = include_youth
            if include_reserves:
                kwargs["include_reserves"] = include_reserves
            if status_filter is not None:
                kwargs["status_filter"] = status_filter
            if not strict_filters:
                kwargs["strict_filters"] = strict_filters
            if group_by is not None:
                kwargs["group_by"] = group_by
            return await cal_svc(**kwargs)

        # Actions equipes / classement : pré-résolution nécessaire
        target_org_id = organisme_id
        if not target_org_id and club_name:
            resolved_clubs, _ = await resolve_club_svc(
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

            if effective_filtre:
                resolved_clubs, _ = await disambiguate_clubs_by_category(
                    resolved_clubs,
                    categorie=effective_filtre,
                    club_name=club_name,
                    season_id=season_id,
                )

            if is_real_ambiguity(resolved_clubs, club_name):
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

            primary_club = get_primary_club(resolved_clubs, club_name)
            target_org_id = (
                primary_club.get("organisme_id")
                if primary_club
                else resolved_clubs[0].get("organisme_id")
            )

        if action == "equipes":
            if not target_org_id:
                return [
                    {
                        "error": "organisme_id requis pour l'action 'equipes' (la résolution du club_name a échoué)."
                    }
                ]
            result = await equipes_svc(
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

            if not effective_poule_id and target_org_id:
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

                resolved_pid = await resolve_pid_svc(
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

            return await classement_svc(
                poule_id=effective_poule_id,
                force_refresh=force_refresh,
                target_organisme_id=target_org_id,
                target_num=target_num,
            )
        return [{"error": f"Action inconnue: {action}"}]
    except Exception as e:
        raise handle_api_error(e) from e


@track_tool_usage("ffbb_head_to_head")
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Compare deux équipes et analyse leurs confrontations directes (H2H) et dynamiques."""
    h2h_svc = _get_server_service(
        "ffbb_head_to_head_service", ffbb_head_to_head_service
    )
    try:
        await _safe_report_progress(
            ctx, 0, total=2, message="Analyse du face-à-face..."
        )
        eff_club_a = club_a or club_name
        eff_org_a = organisme_id_a or organisme_id
        eff_club_b = club_b or adversaire
        eff_org_b = organisme_id_b or adversaire_id
        eff_eng_a = engagement_id_a or engagement_id
        eff_eng_b = engagement_id_b

        result = await h2h_svc(
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


def register_club_tools(mcp: MCPServer) -> None:
    """Enregistre les outils club auprès du serveur FastMCP."""
    mcp.add_tool(
        ffbb_club,
        name="ffbb_club",
        title="Outils agrégés club",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_head_to_head,
        name="ffbb_head_to_head",
        title="Face-à-Face & Comparaison d'équipes (H2H)",
        annotations=_READONLY_ANNOTATIONS,
    )
