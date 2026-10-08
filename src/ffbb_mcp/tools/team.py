"""Outils MCP FastMCP pour les équipes : bilan, résolution, résumé, dernier et prochain match."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import Context  # noqa: TC002
from pydantic import Field

if TYPE_CHECKING:
    from mcp.server import MCPServer

from ffbb_mcp.aliases_registry import get_aliases_registry
from ffbb_mcp.presentation import (
    build_provenance_block,
    format_source_label,
)
from ffbb_mcp.services import (
    ffbb_bilan_service,
    ffbb_find_team_candidates_service,
    ffbb_get_classement_service,
    ffbb_last_result_service,
    ffbb_next_match_service,
    ffbb_resolve_team_service,
    ffbb_saison_bilan_service,
    format_compact_classement,
    get_poule_service,
)
from ffbb_mcp.services.common import McpError
from ffbb_mcp.utils import parse_categorie

from .common import (
    _READONLY_ANNOTATIONS,
    _get_server_service,
    _safe_report_progress,
    handle_api_error,
    track_tool_usage,
)

logger = logging.getLogger(__name__)


def _require_club_identifier(
    *,
    organisme_id: Any = None,
    club_name: Any = None,
    engagement_id: Any = None,
    poule_id: Any = None,
    competition_id: Any = None,
) -> None:
    """Valide qu'au moins un identifiant de club est fourni.

    Lève McpError avec un message explicite au lieu de laisser passer
    None comme chaîne de recherche (qui produirait 'Club None introuvable').
    """
    if not any(
        v is not None and str(v).strip() not in ("", "None")
        for v in (organisme_id, club_name, engagement_id, poule_id, competition_id)
    ):
        raise McpError(
            "Paramètre manquant : fournir au moins un identifiant de club "
            "(organisme_id, club_name, engagement_id, poule_id ou competition_id)."
        )


# Enveloppes de ffbb_last_result/next_match exploitables dans team_summary :
# "ok" (match trouvé) ou "no_upcoming_match" (vide explicite avec présentation).
# Les enveloppes d'erreur (ambiguous/not_found/error) ne doivent pas passer
# pour des matchs.
_SUMMARY_MATCH_STATUSES = frozenset({"ok", "no_upcoming_match"})


def _accepted_match_envelope(raw: Any) -> dict[str, Any] | None:
    """Ne retient qu'une enveloppe de match exploitable, sinon None."""
    if isinstance(raw, dict) and raw.get("status") in _SUMMARY_MATCH_STATUSES:
        return raw
    return None


@track_tool_usage("ffbb_bilan")
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Bilan statistique brut (V/D, paniers, répartition par équipe).

    Pour une vue d'ensemble avec calendrier/classement, préférer `ffbb_team_summary`.
    Pour le parcours multi-phases/coupes, préférer `ffbb_bilan_saison`.
    """
    _require_club_identifier(
        organisme_id=organisme_id,
        club_name=club_name,
        engagement_id=engagement_id,
        poule_id=poule_id,
        competition_id=competition_id,
    )
    bilan_svc = _get_server_service("ffbb_bilan_service", ffbb_bilan_service)
    try:
        await _safe_report_progress(ctx, 0, total=3, message="Résolution du club…")
        effective_refresh = force_refresh
        effective_cat = categorie
        reg = get_aliases_registry()
        is_known_div = bool(categorie and reg.lookup(categorie) is not None)
        if (
            not is_known_div
            and numero_equipe is not None
            and numero_equipe > 1
            and categorie
            and str(numero_equipe) not in categorie
        ):
            effective_cat = f"{categorie}{numero_equipe}"

        result = await bilan_svc(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=effective_cat,
            numero_equipe=numero_equipe,
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


@track_tool_usage("ffbb_resolve_team")
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

    Politique : si une catégorie sans numéro (ex: 'U18M') correspond à plusieurs équipes (ex: U18M1, U18M2),
    retourne 'ambiguous' (confiance 0.5) sans trancher arbitrairement.
    Pour des suggestions heuristiques ordonnées (U18M1 à 0.85), utiliser `ffbb_find_team_candidates`.
    """
    resolve_svc = _get_server_service(
        "ffbb_resolve_team_service", ffbb_resolve_team_service
    )
    try:
        return await resolve_svc(
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


@track_tool_usage("ffbb_find_team_candidates")
async def ffbb_find_team_candidates(
    club_name: Annotated[
        str | None,
        Field(
            description="Nom du club ou de la CTC (ex: 'Cournon', 'Stade Clermontois'). Requis si organisme_id absent."
        ),
    ] = None,
    organisme_id: Annotated[
        int | str | None,
        Field(description="ID FFBB du club (ex: '9289'). Requis si club_name absent."),
    ] = None,
    categorie: Annotated[
        str | None,
        Field(
            description=(
                "Catégorie, étiquette ou division demandée (ex: 'U13F1', 'U13F', 'U15M', 'NM3', 'Senior'). "
                "L'outil extrait tranche d'âge, genre et numéro recherchés pour isoler les candidats."
            )
        ),
    ] = None,
    sexe: Annotated[
        Literal["M", "F", "MIXTE"] | None,
        Field(description="Genre de l'équipe ('M', 'F' ou 'MIXTE')."),
    ] = None,
    numero_equipe: Annotated[
        int | None,
        Field(description="Numéro d'équipe facultatif (ex: 1, 2)."),
    ] = None,
    season_id: Annotated[
        int | str | None,
        Field(description="ID de la saison FFBB (optionnel)."),
    ] = None,
    include_next_match: Annotated[
        bool,
        Field(
            description="Si True (défaut), récupère le prochain match programmé pour chaque candidat."
        ),
    ] = True,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force le rafraîchissement des données."),
    ] = False,
) -> dict[str, Any]:
    """Recherche et ordonne les équipes candidates d'un club/CTC pour désambiguïser avant tout calendrier/résultat.

    Évite la confusion entre équipe fanion sans numéro (ex: U13F en régional) et équipe réserve (ex: U13F2 en départemental).
    Retourne la liste des candidats triés avec confiance, motif, détails de compétition et prochain match.

    Politique : contrairement à `ffbb_resolve_team` (garde-fou strict), recommande l'équipe fanion (confiance 0.85) en l'absence de numéro.
    """
    candidates_svc = _get_server_service(
        "ffbb_find_team_candidates_service", ffbb_find_team_candidates_service
    )
    try:
        return await candidates_svc(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
            sexe=sexe,
            numero_equipe=numero_equipe,
            season_id=season_id,
            include_next_match=include_next_match,
            force_refresh=force_refresh,
        )
    except Exception as e:
        raise handle_api_error(e) from e


@track_tool_usage("ffbb_team_summary")
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
    include: Annotated[
        list[str] | None,
        Field(
            description="Sections à inclure : 'bilan', 'last', 'next', 'classement', 'dynamique'. Défaut: ['bilan', 'last', 'next', 'classement']."
        ),
    ] = None,
    detail: Annotated[
        bool,
        Field(
            description="Si True, inclut les colonnes détaillées du classement (pénalités, forfaits, logos)."
        ),
    ] = False,
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force un rafraichissement des donnees"),
    ] = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Synthèse recommandée d'une équipe (résultats, prochain match, classement, dynamique en 1 appel).

    Préférer cet outil pour toute question d'équipe ('Comment vont les U13M2 ?', 'NM3', etc.).
    Pour une analyse multi-phases ou coupes, utiliser `ffbb_bilan_saison`.
    """
    _require_club_identifier(
        organisme_id=organisme_id,
        club_name=club_name,
        engagement_id=engagement_id,
        poule_id=poule_id,
        competition_id=competition_id,
    )

    effective_include: set[str] = (
        set(include) if include is not None else {"bilan", "last", "next", "classement"}
    )
    if isinstance(include, str):
        effective_include = {s.strip() for s in include.split(",")}

    want_bilan = "bilan" in effective_include
    want_last = "last" in effective_include
    want_next = "next" in effective_include
    want_classement = "classement" in effective_include
    want_dynamique = "dynamique" in effective_include

    resolve_svc = _get_server_service(
        "ffbb_resolve_team_service", ffbb_resolve_team_service
    )
    bilan_svc = _get_server_service("ffbb_bilan_service", ffbb_bilan_service)
    last_svc = _get_server_service("ffbb_last_result_service", ffbb_last_result_service)
    next_svc = _get_server_service("ffbb_next_match_service", ffbb_next_match_service)
    classement_svc = _get_server_service(
        "ffbb_get_classement_service", ffbb_get_classement_service
    )
    poule_svc = _get_server_service("get_poule_service", get_poule_service)

    try:
        await _safe_report_progress(ctx, 0, total=3, message="Résolution de l'équipe…")
        parsed_cat = parse_categorie(categorie) if categorie else None
        effective_cat = categorie
        reg = get_aliases_registry()
        is_known_div = bool(categorie and reg.lookup(categorie) is not None)
        if (
            not is_known_div
            and parsed_cat
            and parsed_cat.numero_equipe is None
            and numero_equipe is not None
        ):
            effective_cat = f"{categorie}{numero_equipe}"

        # Résoudre l'équipe d'abord pour obtenir organisme_id et catégorie
        resolve_result = await resolve_svc(
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

        effective_org_id = resolved_org_id
        if not effective_org_id:
            return {"error": "Impossible de résoudre le club"}

        has_team_context = (
            bool(categorie) or engagement_id is not None or resolved_team is not None
        )

        effective_poule_id = poule_id or (
            resolved_team.get("poule_id") if isinstance(resolved_team, dict) else None
        )
        effective_engagement_id = engagement_id or (
            resolved_team.get("engagement_id")
            if isinstance(resolved_team, dict)
            else None
        )
        effective_competition_id = competition_id or (
            resolved_team.get("competition_id")
            if isinstance(resolved_team, dict)
            else None
        )

        # Validation de cohérence : si un engagement_id et un poule_id sont tous les deux fournis,
        # ils doivent correspondre à la même équipe / poule.
        if (
            engagement_id is not None
            and poule_id is not None
            and isinstance(resolved_team, dict)
        ):
            team_poule = str(resolved_team.get("poule_id") or "").strip()
            given_poule = str(poule_id).strip()
            if team_poule and given_poule and team_poule != given_poule:
                comp_name = resolved_team.get("competition") or "cette compétition"
                team_name = (
                    resolved_team.get("nom_equipe")
                    or resolved_team.get("team_label")
                    or "l'équipe"
                )

                return {
                    "status": "error",
                    "error": (
                        f"Incompatibilité d'identifiants : l'engagement '{engagement_id}' ({team_name}, {comp_name}) "
                        f"appartient à la poule '{team_poule}', et non à la poule '{given_poule}' fournie."
                    ),
                    "code": "incompatible_identifiers",
                    "engagement_id": str(engagement_id),
                    "engagement_poule_id": team_poule,
                    "provided_poule_id": given_poule,
                    "suggestion": (
                        f"Omettez 'poule_id' pour utiliser automatiquement la poule '{team_poule}' de cet engagement, "
                        f"ou vérifiez les identifiants fournis."
                    ),
                    "presentation": {
                        "short_answer": (
                            f"Erreur d'identifiants : l'engagement {engagement_id} appartient à la poule {team_poule} "
                            f"et ne peut pas être combiné avec la poule {given_poule}."
                        ),
                        "detail_line": "Requête contradictoire rejetée pour préserver l'intégrité des données.",
                        "source_label": format_source_label(),
                        "warnings": ["incompatible_identifiers"],
                    },
                    "warnings": ["incompatible_identifiers"],
                }

        if effective_org_id and has_team_context:
            await _safe_report_progress(
                ctx, 1, total=3, message="Récupération bilan et matchs en parallèle…"
            )

        # Lancer les coroutines en parallèle
        bilan_coro = bilan_svc(
            club_name=None,
            organisme_id=effective_org_id,
            categorie=effective_cat or categorie,
            engagement_id=effective_engagement_id,
            competition_id=effective_competition_id,
            competition_type=competition_type,
            poule_id=effective_poule_id,
            season_id=season_id,
            force_refresh=force_refresh,
        )

        async def _safe_run(coro):
            if coro is None:
                return None
            try:
                return await coro
            except Exception as ex:
                return ex

        last_coro = (
            last_svc(
                organisme_id=effective_org_id,
                categorie=categorie,
                numero_equipe=resolved_num,
                engagement_id=effective_engagement_id,
                competition_id=effective_competition_id,
                competition_type=competition_type,
                poule_id=effective_poule_id,
                season_id=season_id,
                force_refresh=force_refresh,
            )
            if (want_last and effective_org_id and has_team_context)
            else None
        )

        next_coro = (
            next_svc(
                organisme_id=effective_org_id,
                categorie=categorie,
                numero_equipe=resolved_num,
                engagement_id=effective_engagement_id,
                competition_id=effective_competition_id,
                competition_type=competition_type,
                poule_id=effective_poule_id,
                season_id=season_id,
                force_refresh=force_refresh,
            )
            if (want_next and effective_org_id and has_team_context)
            else None
        )

        cl_coro = (
            classement_svc(
                poule_id=effective_poule_id,
                force_refresh=force_refresh,
                target_organisme_id=effective_org_id,
                target_num=resolved_num,
            )
            if (want_classement and effective_poule_id)
            else None
        )

        poule_coro = (
            poule_svc(effective_poule_id, force_refresh=force_refresh)
            if (want_classement and effective_poule_id)
            else None
        )

        gather_results = await asyncio.gather(
            _safe_run(bilan_coro),
            _safe_run(last_coro),
            _safe_run(next_coro),
            _safe_run(cl_coro),
            _safe_run(poule_coro),
            return_exceptions=True,
        )

        raw_bilan: Any = gather_results[0]
        raw_last: Any = gather_results[1]
        raw_next: Any = gather_results[2]
        raw_classement: Any = gather_results[3]
        raw_poule_data: Any = gather_results[4]

        bilan = raw_bilan if isinstance(raw_bilan, dict) else {"error": str(raw_bilan)}
        last_match = _accepted_match_envelope(raw_last)
        next_match = _accepted_match_envelope(raw_next)

        # Si le poule_id n'était pas connu au départ, le résoudre depuis bilan.phase_courante
        phase_courante = (
            bilan.get("phase_courante") if isinstance(bilan, dict) else None
        )
        if (
            want_classement
            and not effective_poule_id
            and isinstance(phase_courante, dict)
        ):
            effective_poule_id = phase_courante.get("poule_id")
            if effective_poule_id:
                try:
                    gather_res = await asyncio.gather(
                        classement_svc(
                            poule_id=effective_poule_id,
                            force_refresh=force_refresh,
                            target_organisme_id=effective_org_id,
                            target_num=resolved_num,
                        ),
                        poule_svc(effective_poule_id, force_refresh=force_refresh),
                        return_exceptions=True,
                    )
                    c_res = gather_res[0] if len(gather_res) > 0 else None
                    p_res = gather_res[1] if len(gather_res) > 1 else None
                    raw_classement = c_res if isinstance(c_res, list) else []
                    raw_poule_data = p_res if isinstance(p_res, dict) else None
                except Exception as exc:
                    logger.debug("Erreur récupération classement post-bilan: %s", exc)
                    raw_classement = []
                    raw_poule_data = None

        classement_items = raw_classement if isinstance(raw_classement, list) else []
        poule_data = raw_poule_data if isinstance(raw_poule_data, dict) else None

        # Construire le classement compact (RSG Art. 28)
        compact_classement = format_compact_classement(
            classement_list=classement_items,
            poule_data=poule_data,
            detail=detail,
            target_organisme_id=effective_org_id,
            target_num=resolved_num,
        )

        # 4. Cohérence et retry automatique côté serveur
        warnings_list: list[str] = []
        bilan_pos = (
            phase_courante.get("position") if isinstance(phase_courante, dict) else None
        )
        bilan_j = (
            phase_courante.get("match_joues")
            if isinstance(phase_courante, dict)
            else None
        )
        target_pos = compact_classement.get("target_pos")
        target_j = None
        if compact_classement.get("rows") and target_pos is not None:
            for row in compact_classement["rows"]:
                if len(row) > 3 and row[0] == target_pos:
                    target_j = row[3]
                    break

        incoherence_position = False
        if bilan_pos is not None and target_pos is not None:
            try:
                if int(bilan_pos) != int(target_pos):
                    incoherence_position = True
            except (ValueError, TypeError):
                pass

        if bilan_j is not None and target_j is not None:
            try:
                if int(bilan_j) != int(target_j):
                    incoherence_position = True
            except (ValueError, TypeError):
                pass

        if incoherence_position:
            warnings_list.append("incoherence_position")
            if not force_refresh:
                # Retry côté serveur avec force_refresh=True
                try:
                    bilan = await bilan_svc(
                        club_name=None,
                        organisme_id=effective_org_id,
                        categorie=effective_cat or categorie,
                        engagement_id=effective_engagement_id,
                        competition_id=effective_competition_id,
                        competition_type=competition_type,
                        poule_id=effective_poule_id,
                        season_id=season_id,
                        force_refresh=True,
                    )
                    phase_courante = (
                        bilan.get("phase_courante") if isinstance(bilan, dict) else None
                    )
                    if want_classement and effective_poule_id:
                        gather_ref = await asyncio.gather(
                            classement_svc(
                                poule_id=effective_poule_id,
                                force_refresh=True,
                                target_organisme_id=effective_org_id,
                                target_num=resolved_num,
                            ),
                            poule_svc(effective_poule_id, force_refresh=True),
                            return_exceptions=True,
                        )
                        c_ref = gather_ref[0] if len(gather_ref) > 0 else None
                        p_ref = gather_ref[1] if len(gather_ref) > 1 else None
                        classement_items = c_ref if isinstance(c_ref, list) else []
                        poule_data = p_ref if isinstance(p_ref, dict) else None
                        compact_classement = format_compact_classement(
                            classement_list=classement_items,
                            poule_data=poule_data,
                            detail=detail,
                            target_organisme_id=effective_org_id,
                            target_num=resolved_num,
                        )
                        target_pos = compact_classement.get("target_pos")
                except Exception as exc:
                    logger.debug("Erreur retry force_refresh team_summary: %s", exc)

        # Warning poule incomplète ou non démarrée
        if (
            want_classement
            and not compact_classement.get("rows")
            and "classement_indisponible" not in warnings_list
        ):
            warnings_list.append("classement_indisponible")

        # 5. Phases multiples (autres_phases)
        autres_phases: list[dict[str, Any]] = []
        if isinstance(bilan, dict):
            all_phases = bilan.get("phases") or []
            cur_pid_str = str(effective_poule_id or "")
            seen_pids = {cur_pid_str} if cur_pid_str else set()
            for p in all_phases:
                if not isinstance(p, dict):
                    continue
                p_pid = str(p.get("poule_id") or "")
                p_num = str(p.get("numero_equipe") or "")
                if resolved_num and p_num and p_num != str(resolved_num):
                    continue
                if p_pid and p_pid not in seen_pids:
                    seen_pids.add(p_pid)
                    autres_phases.append(
                        {
                            "poule_id": p_pid,
                            "label": p.get("competition") or f"Poule {p_pid}",
                        }
                    )

        await _safe_report_progress(ctx, 3, total=3, message="Résumé prêt.")
        team_data = (
            resolved_team
            or (next_match.get("team") if isinstance(next_match, dict) else None)
            or (last_match.get("team") if isinstance(last_match, dict) else None)
            or (bilan.get("team") if isinstance(bilan, dict) else None)
        )

        dynamique_data = None
        if want_dynamique and isinstance(bilan, dict):
            eq_bilans = bilan.get("equipes_bilan")
            num_str = str(resolved_num)
            if isinstance(eq_bilans, dict) and isinstance(eq_bilans.get(num_str), dict):
                dynamique_data = eq_bilans[num_str].get("dynamique")
            if dynamique_data is None:
                dynamique_data = bilan.get("dynamique")

        def _clean_match_item(m: dict[str, Any] | None) -> dict[str, Any] | None:
            if not isinstance(m, dict):
                return None
            inner = m.get("match")
            match_data: dict[str, Any] = inner if isinstance(inner, dict) else m
            cleaned = {
                k: v
                for k, v in match_data.items()
                if k
                not in (
                    "club_resolu",
                    "team",
                    "_meta",
                    "status",
                    "data",
                    "presentation",
                    "provenance",
                )
                and v is not None
            }
            return cleaned or None

        cleaned_last_match = _clean_match_item(last_match) if want_last else None
        cleaned_next_match = _clean_match_item(next_match) if want_next else None

        team_name_str = (
            (team_data.get("team_label") if isinstance(team_data, dict) else None)
            or (team_data.get("nom_equipe") if isinstance(team_data, dict) else None)
            or (team_data.get("nom") if isinstance(team_data, dict) else None)
            or club_name
            or "Équipe"
        )
        raw_summary = bilan.get("bilan_total") if isinstance(bilan, dict) else None
        summary_dict: dict[str, Any] = (
            raw_summary if isinstance(raw_summary, dict) else {}
        )
        has_real_bilan = (
            isinstance(raw_summary, dict)
            and bool(raw_summary)
            and any(
                k in raw_summary
                for k in ("victoires", "defaites", "gagnes", "perdus", "match_joues")
            )
        )
        if not has_real_bilan:
            bilan_phrase = "bilan non disponible"
        else:
            v_count = summary_dict.get("victoires")
            if v_count is None:
                v_count = summary_dict.get("gagnes", 0)
            d_count = summary_dict.get("defaites")
            if d_count is None:
                d_count = summary_dict.get("perdus", 0)
            n_count = summary_dict.get("nuls", 0)
            v_label = "victoire" if v_count == 1 else "victoires"
            d_label = "défaite" if d_count == 1 else "défaites"
            bilan_phrase = f"{v_count} {v_label}, {d_count} {d_label}"
            if n_count:
                n_label = "nul" if n_count == 1 else "nuls"
                bilan_phrase += f", {n_count} {n_label}"

        # Formater la dynamique en texte lisible (seulement si demandée)
        dyn_str = ""
        if want_dynamique and isinstance(dynamique_data, dict):
            forme_str = dynamique_data.get("forme_str", "")
            raw_serie = dynamique_data.get("serie_actuelle")
            serie = raw_serie if isinstance(raw_serie, dict) else {}
            serie_label = serie.get("label", "")
            parts = []
            if forme_str:
                parts.append(f"forme {forme_str}")
            if serie_label:
                parts.append(serie_label)
            if parts:
                dyn_str = f" ({', '.join(parts)})"

        # 7. presentation.short_answer : position, points et prochain match complet
        target_pts = None
        if compact_classement.get("rows") and target_pos is not None:
            for row in compact_classement["rows"]:
                if len(row) > 2 and row[0] == target_pos:
                    target_pts = row[2]
                    break

        pos_pts_parts: list[str] = []
        if target_pos is not None:
            pos_label = "1er" if target_pos == 1 else f"{target_pos}e"
            pos_pts_parts.append(pos_label)
        if target_pts is not None:
            pts_label = f"{target_pts} pt" if target_pts == 1 else f"{target_pts} pts"
            pos_pts_parts.append(pts_label)

        pos_pts_str = f" ({', '.join(pos_pts_parts)})" if pos_pts_parts else ""
        if has_real_bilan:
            short_ans = (
                f"Bilan pour {team_name_str}{pos_pts_str} : {bilan_phrase}{dyn_str}."
            )
        elif pos_pts_str:
            short_ans = f"Situation pour {team_name_str}{pos_pts_str} : bilan chiffré non disponible{dyn_str}."
        else:
            short_ans = (
                f"Données pour {team_name_str} : bilan chiffré non disponible{dyn_str}."
            )

        if (
            next_match
            and isinstance(next_match, dict)
            and next_match.get("status") != "no_upcoming_match"
        ):
            raw_match = next_match.get("match")
            inner_m: dict[str, Any] = raw_match if isinstance(raw_match, dict) else {}
            next_adv = (
                next_match.get("adversaire")
                or inner_m.get("adversaire")
                or next_match.get("nomEquipe2")
            )
            next_is_home = (
                next_match.get("domicile")
                if next_match.get("domicile") is not None
                else inner_m.get("domicile")
            )
            next_date = (
                next_match.get("date")
                or next_match.get("date_reelle")
                or inner_m.get("date")
            )
            next_heure = (
                next_match.get("heure")
                or next_match.get("heure_reelle")
                or inner_m.get("heure")
            )
            raw_salle = next_match.get("salle_details") or inner_m.get("salle_details")
            salle_info: dict[str, Any] = (
                raw_salle if isinstance(raw_salle, dict) else {}
            )
            next_lieu = (
                salle_info.get("nom")
                or salle_info.get("libelle")
                or next_match.get("nomSalle")
                or inner_m.get("nomSalle")
                or next_match.get("lieu")
                or inner_m.get("lieu")
            )
            next_ville = (
                salle_info.get("ville")
                or salle_info.get("commune")
                or next_match.get("villeSalle")
                or inner_m.get("villeSalle")
                or next_match.get("ville")
                or inner_m.get("ville")
            )

            if next_adv:
                verb = (
                    "reçoit"
                    if next_is_home is True
                    else ("se déplace chez" if next_is_home is False else "face à")
                )
                dt_parts = []
                if next_date:
                    dt_parts.append(f"le {next_date}")
                if next_heure:
                    dt_parts.append(f"à {next_heure}")
                dt_phrase = f" {' '.join(dt_parts)}" if dt_parts else ""
                venue_parts = [p for p in (next_lieu, next_ville) if p]
                venue_phrase = f" ({', '.join(venue_parts)})" if venue_parts else ""
                short_ans += (
                    f" Prochain match : {verb} {next_adv}{dt_phrase}{venue_phrase}."
                )

        detail_parts = []
        if isinstance(last_match, dict) and "presentation" in last_match:
            detail_parts.append(
                f"Dernier résultat : {last_match['presentation'].get('short_answer', '')}"
            )
        elif cleaned_last_match:
            detail_parts.append("Dernier match enregistré.")

        if isinstance(next_match, dict) and "presentation" in next_match:
            detail_parts.append(
                f"Prochain match : {next_match['presentation'].get('short_answer', '')}"
            )
        elif cleaned_next_match:
            detail_parts.append("Prochain match programmé.")

        detail_line = (
            " ".join(detail_parts)
            if detail_parts
            else "Aucun match récent ou programmé."
        )

        # Agréger et dédupliquer les avertissements des sous-sections
        def _collect_sub_warnings(source: dict[str, Any] | None) -> None:
            if not isinstance(source, dict):
                return
            src_warns = source.get("warnings") or []
            if isinstance(src_warns, list):
                for w in src_warns:
                    w_str = str(w).strip()
                    if w_str and w_str not in warnings_list:
                        warnings_list.append(w_str)
            pres = source.get("presentation")
            if isinstance(pres, dict):
                p_warns = pres.get("warnings") or []
                if isinstance(p_warns, list):
                    for w in p_warns:
                        w_str = str(w).strip()
                        if w_str and w_str not in warnings_list:
                            warnings_list.append(w_str)

        _collect_sub_warnings(bilan)
        _collect_sub_warnings(last_match)
        _collect_sub_warnings(next_match)
        if compact_classement.get("warning"):
            cw = str(compact_classement["warning"]).strip()
            if cw and cw not in warnings_list:
                warnings_list.append(cw)

        presentation = {
            "short_answer": short_ans,
            "detail_line": detail_line,
            "source_label": format_source_label(),
            "warnings": warnings_list,
        }

        meta_obj = bilan.get("_meta") if isinstance(bilan, dict) else None
        is_cache_hit = (
            not force_refresh
            and isinstance(meta_obj, dict)
            and (bool(meta_obj.get("cache_hit")) or meta_obj.get("source") == "cache")
        )
        resource_ids = {
            "organisme_id": str(effective_org_id) if effective_org_id else None,
            "engagement_id": str(engagement_id) if engagement_id else None,
            "competition_id": str(competition_id) if competition_id else None,
            "poule_id": str(effective_poule_id) if effective_poule_id else None,
        }
        provenance = build_provenance_block(
            source="cache" if is_cache_hit else "ffbb_api_live",
            cache_status="hit" if is_cache_hit else "miss",
            resource_ids=resource_ids,
        )

        res_payload: dict[str, Any] = {
            "status": "ok",
            "team": team_data,
            "phase_courante": phase_courante,
            "last_match": cleaned_last_match if want_last else None,
            "next_match": cleaned_next_match if want_next else None,
        }
        if want_bilan:
            res_payload["summary"] = (
                bilan.get("bilan_total") if isinstance(bilan, dict) else None
            )
        if want_classement:
            res_payload["classement"] = compact_classement
        if want_dynamique:
            res_payload["dynamique"] = dynamique_data
        if autres_phases:
            res_payload["autres_phases"] = autres_phases

        res_payload["presentation"] = presentation
        res_payload["provenance"] = provenance
        return res_payload

    except Exception as e:
        raise handle_api_error(e) from e


@track_tool_usage("ffbb_last_result")
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

    last_svc = _get_server_service("ffbb_last_result_service", ffbb_last_result_service)
    try:
        effective_refresh = force_refresh
        effective_num = numero_equipe if numero_equipe is not None else 1
        effective_cat = categorie or ""
        if categorie:
            parsed = parse_categorie(categorie)
            if parsed and parsed.numero_equipe is not None:
                effective_num = parsed.numero_equipe
        return await last_svc(
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
    except Exception as e:
        raise handle_api_error(e) from e


@track_tool_usage("ffbb_next_match")
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

    next_svc = _get_server_service("ffbb_next_match_service", ffbb_next_match_service)
    try:
        effective_num = numero_equipe if numero_equipe is not None else 1
        effective_cat = categorie or ""
        if categorie:
            parsed = parse_categorie(categorie)
            if parsed and parsed.numero_equipe is not None:
                effective_num = parsed.numero_equipe
        return await next_svc(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=effective_cat,
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


@track_tool_usage("ffbb_bilan_saison")
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Bilan multi-phases approfondi d'une équipe sur la saison (phases 1/2, coupes, play-offs).

    Agrège le parcours successif avec cumul saisonnier. Pour une synthèse rapide, préférer `ffbb_team_summary`.
    """
    saison_bilan_svc = _get_server_service(
        "ffbb_saison_bilan_service", ffbb_saison_bilan_service
    )
    try:
        await _safe_report_progress(ctx, 0, total=1, message="Calcul du bilan saison…")
        effective_refresh = force_refresh
        effective_num = numero_equipe
        effective_cat = categorie
        if categorie:
            parsed = parse_categorie(categorie)
            if parsed.numero_equipe is not None:
                effective_num = parsed.numero_equipe

        result = await saison_bilan_svc(
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


def register_team_tools(mcp: MCPServer) -> None:
    """Enregistre les outils d'équipe auprès du serveur FastMCP."""
    mcp.add_tool(
        ffbb_bilan,
        name="ffbb_bilan",
        title="Bilan complet toutes phases",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_resolve_team,
        name="ffbb_resolve_team",
        title="Résolution d'équipe",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_find_team_candidates,
        name="ffbb_find_team_candidates",
        title="Recherche et désambiguïsation d'équipes candidates",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_team_summary,
        name="ffbb_team_summary",
        title="Résumé complet d'équipe",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_last_result,
        name="ffbb_last_result",
        title="Dernier résultat d'équipe",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_next_match,
        name="ffbb_next_match",
        title="Prochain match d'équipe",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_bilan_saison,
        name="ffbb_bilan_saison",
        title="Bilan détaillé de saison",
        annotations=_READONLY_ANNOTATIONS,
    )
