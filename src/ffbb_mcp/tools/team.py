"""Outils MCP FastMCP pour les équipes : bilan, résolution, résumé, dernier et prochain match."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import Context  # noqa: TC002
from pydantic import Field

if TYPE_CHECKING:
    from mcp.server import MCPServer

from ffbb_mcp.presentation import (
    build_provenance_block,
    format_source_label,
)
from ffbb_mcp.services import (
    ffbb_bilan_service,
    ffbb_find_team_candidates_service,
    ffbb_last_result_service,
    ffbb_next_match_service,
    ffbb_resolve_team_service,
    ffbb_saison_bilan_service,
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
    """Bilan complet d'une équipe toutes phases confondues en UN seul appel (V/D/N, paniers, phases).

    Outil prioritaire pour 'quel est le bilan de X ?' ou 'résultats de U11M1'.
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
        if (
            numero_equipe is not None
            and numero_equipe > 1
            and categorie
            and str(numero_equipe) not in categorie
        ):
            effective_cat = f"{categorie}{numero_equipe}"

        result = await bilan_svc(
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
    force_refresh: Annotated[
        bool,
        Field(description="Si True, force un rafraichissement des donnees"),
    ] = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Résumé complet d'équipe : bilan, classement, dernier et prochain match en un seul appel.

    Résout NM3, PNM, NF1, etc. vers la bonne équipe. En cas d'ambiguïté, suggère les candidats.
    """
    _require_club_identifier(
        organisme_id=organisme_id,
        club_name=club_name,
        engagement_id=engagement_id,
        poule_id=poule_id,
        competition_id=competition_id,
    )
    resolve_svc = _get_server_service(
        "ffbb_resolve_team_service", ffbb_resolve_team_service
    )
    bilan_svc = _get_server_service("ffbb_bilan_service", ffbb_bilan_service)
    last_svc = _get_server_service("ffbb_last_result_service", ffbb_last_result_service)
    next_svc = _get_server_service("ffbb_next_match_service", ffbb_next_match_service)

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

        # last_result et next_match nécessitent organisme_id
        effective_org_id = resolved_org_id

        if not effective_org_id:
            return {"error": "Impossible de résoudre le club"}

        # La présence de `categorie` ne doit pas conditionner ces appels : quand
        # l'équipe est désambiguïsée par engagement_id/poule_id seuls (ex: brassage
        # U13M), les services sous-jacents résolvent très bien sans catégorie
        # (filtre engagement_id). Sans cela, next_match restait null alors que
        # find_team_candidates trouvait le match via le même engagement.
        has_team_context = (
            bool(categorie) or engagement_id is not None or resolved_team is not None
        )

        if effective_org_id and has_team_context:
            await _safe_report_progress(
                ctx, 1, total=3, message="Récupération bilan et matchs en parallèle…"
            )

        # Lancer bilan + last_result + next_match en parallèle
        # On passe effective_org_id au lieu de club_name pour éviter une double résolution
        bilan_coro = bilan_svc(
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

        if effective_org_id and has_team_context:
            last_coro = last_svc(
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
            next_coro = next_svc(
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
            gather_results = await asyncio.gather(
                bilan_coro, last_coro, next_coro, return_exceptions=True
            )
            raw_bilan: Any = gather_results[0]
            raw_last: Any = gather_results[1]
            raw_next: Any = gather_results[2]
            # Normaliser les exceptions et types en dicts d'erreur / None.
            # Seules les enveloppes exploitables sont retenues ("ok", ou
            # "no_upcoming_match" qui porte un message explicite) : les
            # enveloppes d'erreur (ambiguous/not_found/error) ne doivent pas
            # passer pour des matchs.
            bilan = (
                raw_bilan if isinstance(raw_bilan, dict) else {"error": str(raw_bilan)}
            )
            last_match = _accepted_match_envelope(raw_last)
            next_match = _accepted_match_envelope(raw_next)
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

        cleaned_last_match = _clean_match_item(last_match)
        cleaned_next_match = _clean_match_item(next_match)

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
        v_count = summary_dict.get("victoires")
        if v_count is None:
            v_count = summary_dict.get("gagnes", 0)
        d_count = summary_dict.get("defaites")
        if d_count is None:
            d_count = summary_dict.get("perdus", 0)
        n_count = summary_dict.get("nuls", 0)
        # Formater la dynamique en texte lisible (jamais de repr dict brut)
        dyn_str = ""
        if isinstance(dynamique_data, dict):
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
        v_label = "victoire" if v_count == 1 else "victoires"
        d_label = "défaite" if d_count == 1 else "défaites"
        bilan_phrase = f"{v_count} {v_label}, {d_count} {d_label}"
        if n_count:
            n_label = "nul" if n_count == 1 else "nuls"
            bilan_phrase += f", {n_count} {n_label}"
        short_ans = f"Bilan pour {team_name_str} : {bilan_phrase}{dyn_str}."

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

        presentation = {
            "short_answer": short_ans,
            "detail_line": detail_line,
            "source_label": format_source_label(),
            "warnings": [],
        }

        resource_ids = {
            "organisme_id": str(effective_org_id) if effective_org_id else None,
            "engagement_id": str(engagement_id) if engagement_id else None,
            "competition_id": str(competition_id) if competition_id else None,
            "poule_id": str(poule_id) if poule_id else None,
        }
        provenance = build_provenance_block(
            source="ffbb_api_live",
            cache_status="miss" if force_refresh else "hit",
            resource_ids=resource_ids,
        )

        return {
            "status": "ok",
            "team": team_data,
            "phase_courante": bilan.get("phase_courante")
            if isinstance(bilan, dict)
            else None,
            "last_match": cleaned_last_match,
            "next_match": cleaned_next_match,
            "summary": bilan.get("bilan_total") if isinstance(bilan, dict) else None,
            "dynamique": dynamique_data,
            "presentation": presentation,
            "provenance": provenance,
        }

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
    saison_bilan_svc = _get_server_service(
        "ffbb_saison_bilan_service", ffbb_saison_bilan_service
    )
    try:
        await _safe_report_progress(ctx, 0, total=1, message="Calcul du bilan saison…")
        effective_refresh = force_refresh
        effective_num = numero_equipe if numero_equipe is not None else 1
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
