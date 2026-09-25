"""Outils MCP FastMCP dédiés aux règlements sportifs officiels FFBB."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import Context  # noqa: TC002
from pydantic import Field

if TYPE_CHECKING:
    from mcp.server import MCPServer

from ffbb_mcp.services import (
    explain_tiebreak_rules_service,
    get_regulation_article_service,
    list_regulations_service,
    search_regulations_service,
)

from .common import (
    _READONLY_ANNOTATIONS,
    _get_server_service,
    _safe_report_progress,
    handle_api_error,
    track_tool_usage,
)


@track_tool_usage("ffbb_search_regulations")
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Recherche plein texte déterministe dans les règlements officiels FFBB, régionaux et départementaux.

    Permet de retrouver les articles pertinents sur les qualifications, montées/descentes,
    brassages jeunes, règles techniques (durée, ballons, zone), forfaits et brûlage.
    Retourne `dict` avec `results[]` (`id`, `document_id`, `article_number`, `article_title`, `relevance_score`, `content`, `topics[]`, `source_url`)
    triés par pertinence ; lecture seule, idempotent, cache SWR.

    Utilise cet outil quand tu ne connais pas le numéro d'article et que tu cherches par
    mots-clés. Ne pas utiliser pour récupérer un article précis — utilise
    `ffbb_get_regulation_article` à la place ; pour lister les documents — utilise
    `ffbb_list_regulations` ; pour expliquer un départage — utilise
    `ffbb_explain_tiebreak_rules` au lieu de chercher le texte. Affûte avec `level`,
    `organizer`, `category` et `limit` pour réduire le bruit.
    """
    svc = _get_server_service("search_regulations_service", search_regulations_service)
    try:
        await _safe_report_progress(
            ctx, 1, total=2, message="Recherche dans les règlements..."
        )
        res = await svc(
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


@track_tool_usage("ffbb_get_regulation_article")
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Récupère le texte intégral et exact d'un article spécifique de règlement sans troncature.

    Retourne `dict` avec `document_id`, `article_number`, `titre`, `contenu` et
    `saison` ; lecture seule, idempotent, sans effet de bord, cache SWR.
    Utilise cet outil quand tu connais le numéro d'article et le document (obtenu via
    `ffbb_list_regulations` ou `ffbb_search_regulations`) et que tu veux le contenu
    verbatim. Ne pas utiliser pour rechercher par mot-clé — utilise
    `ffbb_search_regulations` à la place ; pour lister les documents disponibles —
    utilise `ffbb_list_regulations` ; pour expliquer un départage — utilise
    `ffbb_explain_tiebreak_rules`. Si `document_id` est omis, précise `organizer`
    et `season` pour lever l'ambiguïté.
    """
    svc = _get_server_service(
        "get_regulation_article_service", get_regulation_article_service
    )
    try:
        await _safe_report_progress(
            ctx, 1, total=2, message="Extraction de l'article..."
        )
        res = await svc(
            document_id=document_id,
            article_number=article_number,
            organizer=organizer,
            season=season,
        )
        await _safe_report_progress(ctx, 2, total=2, message="Article extrait.")
        return res
    except Exception as e:
        raise handle_api_error(e) from e


@track_tool_usage("ffbb_explain_tiebreak_rules")
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Fournit les règles officielles de départage en cas d'égalité (Article 28 du RSG FFBB).

    Explique le calcul du point-average particulier (confrontations directes),
    du quotient particulier, et du mini-championnat à 3 équipes ou plus.
    Lecture seule, idempotent, sans effet de bord ; cache SWR court.

    Utilise cet outil uniquement quand deux équipes ou plus sont à égalité de points
    dans une poule et que tu dois expliquer pourquoi l'une est classée devant l'autre.
    Avec `poule_id`, les règles sont appliquées à la poule concrète ; sans, tu obtiens
    les règles génériques. Ne pas utiliser pour rechercher un extrait réglementaire —
    utilise `ffbb_search_regulations` à la place ; pour récupérer le texte d'un article
    précis — utilise `ffbb_get_regulation_article` ; pour lister les règlements
    disponibles — utilise `ffbb_list_regulations`. Ne pas utiliser non plus pour
    obtenir le classement brut — utilise `ffbb_club(action="classement")` — ni pour
    le bilan chiffré — utilise `ffbb_bilan`. Utilise `ffbb_explain_tiebreak_rules`
    au lieu de `ffbb_search_regulations` quand la question porte sur le départage
    et non sur le texte réglementaire.
    """
    svc = _get_server_service(
        "explain_tiebreak_rules_service", explain_tiebreak_rules_service
    )
    try:
        await _safe_report_progress(
            ctx, 1, total=2, message="Chargement des règles de départage..."
        )
        res = await svc(
            poule_id=poule_id,
            season=season,
        )
        await _safe_report_progress(
            ctx, 2, total=2, message="Règles de départage prêtes."
        )
        return res
    except Exception as e:
        raise handle_api_error(e) from e


@track_tool_usage("ffbb_list_regulations")
async def ffbb_list_regulations(
    season: Annotated[
        str,
        Field(description="Saison sportive (défaut '2026-2027')"),
    ] = "2026-2027",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Liste l'ensemble des textes réglementaires fédéraux (RSG, RSP Élite, NM1-NM3, LF2-NF3),
    régionaux (Ligues IDF, Hauts-de-France, AURA...) et départementaux
    (Comités Paris, Nord, Rhône, Puy-de-Dôme...) indexés.

    Retourne l'inventaire complet sous forme `dict` avec `documents[]`
    (`document_id`, `titre`, `organizer`, `level`, `season`) trié par juridiction.
    Lecture seule, idempotent, sans effet de bord ; cache SWR (TTL ≈24h).

    Utilise cet outil pour découvrir les `document_id` disponibles avant d'appeler
    `ffbb_get_regulation_article` ou pour choisir un périmètre avant
    `ffbb_search_regulations`. Ne pas utiliser pour rechercher un extrait textuel —
    utilise `ffbb_search_regulations` à la place ; pour obtenir le texte d'un article
    précis — utilise `ffbb_get_regulation_article` ; pour expliquer un départage —
    utilise `ffbb_explain_tiebreak_rules`. Avec `season`, filtre l'inventaire à la
    saison ciblée (défaut `2026-2027`).
    """
    svc = _get_server_service("list_regulations_service", list_regulations_service)
    try:
        await _safe_report_progress(
            ctx, 1, total=2, message="Inventaire des règlements disponibles..."
        )
        res = await svc(season=season)
        await _safe_report_progress(ctx, 2, total=2, message="Inventaire terminé.")
        return res
    except Exception as e:
        raise handle_api_error(e) from e


def register_regulations_tools(mcp: MCPServer) -> None:
    """Enregistre les outils de règlements auprès du serveur FastMCP."""
    mcp.add_tool(
        ffbb_search_regulations,
        name="ffbb_search_regulations",
        title="Recherche dans les règlements sportifs FFBB",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_get_regulation_article,
        name="ffbb_get_regulation_article",
        title="Lecture exacte d'un article de règlement FFBB",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_explain_tiebreak_rules,
        name="ffbb_explain_tiebreak_rules",
        title="Règles de départage et calcul de classement FFBB",
        annotations=_READONLY_ANNOTATIONS,
    )
    mcp.add_tool(
        ffbb_list_regulations,
        name="ffbb_list_regulations",
        title="Liste des règlements et juridictions FFBB disponibles",
        annotations=_READONLY_ANNOTATIONS,
    )
