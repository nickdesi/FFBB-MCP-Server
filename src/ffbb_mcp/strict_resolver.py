"""Résolveur central, strict et déterministe d'équipes FFBB.

Autorité unique de résolution pour tous les outils analytiques :
- Aucun fallback silencieux
- Aucune substitution de division (NM3 != PNM, NM2 != Élite 2)
- Ordre de priorité déterministe (engagement_id > poule_id > competition_id > org_id > club_name)
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from ffbb_mcp.aliases_registry import get_aliases_registry
from ffbb_mcp.envelope import (
    DataQualityInfo,
    McpResponseEnvelope,
    ProvenanceInfo,
    ResolutionInfo,
    ResponseStatus,
    create_response_envelope,
)
from ffbb_mcp.utils import parse_categorie

logger = logging.getLogger("ffbb-mcp")


class TeamResolutionResult(BaseModel):
    """Résultat structuré de résolution d'équipe."""

    status: ResponseStatus = ResponseStatus.NOT_FOUND
    selected: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    club_resolu: dict[str, Any] | None = None
    ambiguity_message: str | None = None
    clarification_prompt: str | None = None
    match_strategy: list[str] = Field(default_factory=list)
    confidence: float | None = None

    # Compatibilité dictionnaire legacy
    def __getitem__(self, item: str) -> Any:
        if item == "team":
            return self.selected
        if item == "ambiguity":
            return self.ambiguity_message
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "team":
            return self.selected
        if key == "ambiguity":
            return self.ambiguity_message
        return getattr(self, key, default)

    def to_envelope(
        self,
        data: Any = None,
        provenance: ProvenanceInfo | None = None,
        warnings: list[str] | None = None,
    ) -> McpResponseEnvelope[Any]:
        """Convertit le résultat de résolution en enveloppe MCP standardisée."""
        warns = list(warnings or [])
        if self.ambiguity_message and self.status != ResponseStatus.OK:
            warns.append(self.ambiguity_message)
        if self.clarification_prompt:
            warns.append(self.clarification_prompt)

        res_info = ResolutionInfo(
            mode="strict",
            input={},
            selected=self.selected,
            candidates=self.candidates,
            match_strategy=self.match_strategy,
            confidence=self.confidence,
        )
        return create_response_envelope(
            data=data if data is not None else self.selected,
            status=self.status,
            warnings=warns,
            resolution=res_info,
            provenance=provenance,
            data_quality=DataQualityInfo(
                level="high" if self.status == ResponseStatus.OK else "medium"
            ),
        )


def _dedup_same_team_phases(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Déduplique les phases successives d'une même équipe via le moteur canonique."""
    from ffbb_mcp.services.search import _deduplicate_same_team_phases

    return _deduplicate_same_team_phases(teams)


def _is_mock(val: Any) -> bool:
    return hasattr(val, "mock_calls") or hasattr(val, "_mock_self")


def _get_resolve_club_and_org_fn() -> Any:
    import ffbb_mcp.services as svc
    import ffbb_mcp.services.club as club_mod
    import ffbb_mcp.services.search as search_mod

    for mod in [search_mod, club_mod, svc]:
        val = getattr(mod, "resolve_club_and_org", None)
        if val is not None and _is_mock(val):
            return val
    return search_mod.resolve_club_and_org


def _get_equipes_club_service_fn() -> Any:
    import ffbb_mcp.services as svc
    import ffbb_mcp.services.club as club_mod

    for mod in [club_mod, svc]:
        val = getattr(mod, "ffbb_equipes_club_service", None)
        if val is not None and _is_mock(val):
            return val
    return club_mod.ffbb_equipes_club_service


async def resolve_team_strict(
    club_name: str | None = None,
    organisme_id: str | int | None = None,
    categorie: str | None = None,
    numero_equipe: int | None = None,
    engagement_id: str | int | None = None,
    competition_id: str | int | None = None,
    competition_type: str | None = None,
    poule_id: str | int | None = None,
    season_id: str | int | None = None,
    mode: Literal["strict", "suggest", "all"] = "strict",
    force_refresh: bool = False,
    all_teams: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> TeamResolutionResult:
    """Résout une équipe unique de manière déterministe et sans approximation."""
    registry = get_aliases_registry()
    strategies: list[str] = []

    # -----------------------------------------------------------------------
    # PRIORITÉ 1 : engagement_id (Clé absolue)
    # -----------------------------------------------------------------------
    if engagement_id is not None:
        strategies.append("priority_1_engagement_id")
        target_eng_id = str(engagement_id).strip()

        # Si organisme_id ou club_name est déjà fourni, chercher directement dans les équipes du club
        eff_org = str(organisme_id).strip() if organisme_id else None
        if not eff_org and club_name:
            res_club_fn = _get_resolve_club_and_org_fn()
            resolved_clubs, _ = await res_club_fn(
                club_name=club_name,
                organisme_id=None,
                force_refresh=force_refresh,
            )
            if resolved_clubs:
                eff_org = str(resolved_clubs[0].get("organisme_id", ""))

        if eff_org:
            eq_fn = _get_equipes_club_service_fn()
            all_eq = await eq_fn(
                organisme_id=eff_org, force_refresh=force_refresh, season_id=season_id
            )
            matched = [
                e
                for e in all_eq
                if str(e.get("engagement_id") or e.get("team_id") or "").strip()
                == target_eng_id
            ]
            if matched:
                return TeamResolutionResult(
                    status=ResponseStatus.OK,
                    selected=matched[0],
                    candidates=matched,
                    club_resolu={"organisme_id": eff_org},
                    match_strategy=strategies,
                    confidence=1.0,
                )

        # Lookup distant si non trouvé ou organisme non fourni
        from ffbb_mcp.client import FFBBClientFactory

        client = await FFBBClientFactory.get_client_async()
        try:
            eng_data = await client.get_engagement_async(target_eng_id)
        except Exception as e:
            logger.error("Erreur récupération engagement %s: %s", target_eng_id, e)
            eng_data = None

        if eng_data and getattr(eng_data, "idOrganisme", None):
            org_id = str(eng_data.idOrganisme)
            eq_fn = _get_equipes_club_service_fn()
            all_eq = await eq_fn(
                organisme_id=org_id, force_refresh=force_refresh, season_id=season_id
            )
            matched = [
                e
                for e in all_eq
                if str(e.get("engagement_id") or e.get("team_id") or "").strip()
                == target_eng_id
            ]
            if matched:
                return TeamResolutionResult(
                    status=ResponseStatus.OK,
                    selected=matched[0],
                    candidates=matched,
                    club_resolu={"organisme_id": org_id},
                    match_strategy=strategies,
                    confidence=1.0,
                )
        return TeamResolutionResult(
            status=ResponseStatus.NOT_FOUND,
            ambiguity_message=f"Engagement '{target_eng_id}' introuvable pour la saison spécifiée.",
            match_strategy=strategies,
        )

    # -----------------------------------------------------------------------
    # PRIORITÉ 2 & Résolution Club / Organisme
    # -----------------------------------------------------------------------
    if not club_name and not organisme_id and not all_teams:
        return TeamResolutionResult(
            status=ResponseStatus.INVALID_REQUEST,
            ambiguity_message="Fournir au minimum club_name, organisme_id ou engagement_id.",
            match_strategy=strategies,
        )

    target_org_id = str(organisme_id or "")
    if all_teams is not None:
        club_resolu = {
            "nom": club_name or "Club",
            "organisme_id": target_org_id,
        }
    else:
        res_fn = _get_resolve_club_and_org_fn()
        resolved_clubs, _org_data = await res_fn(
            club_name=club_name,
            organisme_id=organisme_id,
            categorie=categorie,
            force_refresh=force_refresh,
        )

        if not resolved_clubs:
            return TeamResolutionResult(
                status=ResponseStatus.NOT_FOUND,
                ambiguity_message=f"Club '{club_name or organisme_id}' introuvable sur les serveurs FFBB.",
                match_strategy=strategies,
            )

        from ffbb_mcp.services.common import (
            disambiguate_clubs_by_category,
            get_primary_club,
            is_real_ambiguity,
        )

        equipes_prefetched: list[dict[str, Any]] | None = None
        if not organisme_id and categorie:
            resolved_clubs, equipes_prefetched = await disambiguate_clubs_by_category(
                resolved_clubs,
                categorie=categorie,
                club_name=club_name,
                season_id=season_id,
            )

        if is_real_ambiguity(resolved_clubs, club_name) and not organisme_id:
            return TeamResolutionResult(
                status=ResponseStatus.AMBIGUOUS,
                candidates=resolved_clubs,
                ambiguity_message=f"Plusieurs clubs correspondent à '{club_name}'. Précisez organisme_id.",
                clarification_prompt=f"Plusieurs clubs correspondent à '{club_name}'. Précisez organisme_id.",
                match_strategy=["ambiguous_club_name"],
            )

        club_resolu = get_primary_club(resolved_clubs, club_name) or resolved_clubs[0]
        target_org_id = str(club_resolu["organisme_id"])

        # Récupérer la totalité des équipes réelles du club (ou utiliser celles préchargées)
        if equipes_prefetched is not None:
            all_teams = equipes_prefetched
        else:
            eq_fn = _get_equipes_club_service_fn()
            all_teams = await eq_fn(
                organisme_id=target_org_id,
                force_refresh=force_refresh,
                season_id=season_id,
            )
    if not all_teams or (
        isinstance(all_teams, list) and len(all_teams) == 1 and "error" in all_teams[0]
    ):
        return TeamResolutionResult(
            status=ResponseStatus.NOT_FOUND,
            club_resolu=club_resolu,
            ambiguity_message=f"Aucune équipe engagée trouvée pour '{club_resolu.get('nom', target_org_id)}'.",
            match_strategy=strategies,
        )

    candidates = [t for t in all_teams if isinstance(t, dict) and "error" not in t]

    # -----------------------------------------------------------------------
    # PRIORITÉ 2 : poule_id
    # -----------------------------------------------------------------------
    if poule_id is not None:
        strategies.append("priority_2_poule_id")
        target_poule = str(poule_id).strip()
        matched_poule = [
            c
            for c in candidates
            if str(c.get("poule_id") or "").strip() == target_poule
        ]
        if matched_poule:
            candidates = matched_poule

    # -----------------------------------------------------------------------
    # PRIORITÉ 3 : competition_id / competition_type
    # -----------------------------------------------------------------------
    if competition_id is not None:
        strategies.append("priority_3_competition_id")
        target_comp = str(competition_id).strip()
        candidates = [
            c
            for c in candidates
            if str(c.get("competition_id") or "").strip() == target_comp
        ]

    if competition_type is not None:
        strategies.append("filter_competition_type")
        target_type = str(competition_type).strip().upper()
        candidates = [
            c
            for c in candidates
            if str(c.get("competition_type") or "").strip().upper() == target_type
        ]

    # -----------------------------------------------------------------------
    # PRIORITÉ 4 : Catégorie normalisée & Division exacte (SANS APPROXIMATION)
    # -----------------------------------------------------------------------
    parsed_req = parse_categorie(categorie) if categorie else None
    target_div = registry.lookup(categorie) if categorie else None
    has_category_metadata = any(
        bool(c.get("categorie") or c.get("competition") or c.get("competition_code"))
        for c in all_teams
    )

    if target_div is not None and has_category_metadata:
        strategies.append(f"division_strict_{target_div.canonical_code}")
        # Filtrer exclusivement les équipes dont la compétition est compatible
        strict_div_candidates: list[dict[str, Any]] = []
        for c in candidates:
            c_code = c.get("competition_code")
            c_nom = c.get("competition")
            c_cat = (c.get("categorie") or "").upper().strip()
            c_sexe = (c.get("sexe") or "").upper().strip()

            is_youth_match = bool(
                target_div.canonical_age
                and (
                    c_cat == target_div.canonical_age
                    or c_cat == target_div.canonical_code
                )
                and (not target_div.sex or not c_sexe or c_sexe == target_div.sex)
            )

            if (
                is_youth_match
                or registry.is_compatible(categorie, c_code, c_nom)
                or registry.is_compatible(
                    categorie, c.get("categorie"), c.get("nom") or c.get("team_label")
                )
            ):
                strict_div_candidates.append(c)

        if not strict_div_candidates:
            # ZÉRO FALLBACK SILENCIEUX ! Retourner not_found avec suggestions
            all_labels = sorted(
                [str(t["team_label"]) for t in all_teams if t.get("team_label")]
            )
            return TeamResolutionResult(
                status=ResponseStatus.NOT_FOUND,
                club_resolu=club_resolu,
                candidates=[{"label": lbl} for lbl in all_labels],
                ambiguity_message=(
                    f"Aucune équipe du club '{club_resolu.get('nom')}' n'est engagée dans la division '{categorie}' "
                    f"(canonique: {target_div.canonical_code}). Aucun rapprochement vers une autre division n'est autorisé."
                ),
                match_strategy=strategies,
            )
        candidates = strict_div_candidates

    elif parsed_req and parsed_req.categorie and has_category_metadata:
        strategies.append(f"category_strict_{parsed_req.categorie}")
        cat_candidates: list[dict[str, Any]] = []
        req_cat = parsed_req.categorie.upper().strip()
        req_sexe = parsed_req.sexe

        for c in candidates:
            c_cat = (c.get("categorie") or "").upper().strip()
            c_sexe = (c.get("sexe") or "").upper().strip()

            # Rapprochement autorisé uniquement SE/SENIOR
            is_cat_match = (c_cat == req_cat) or (
                {c_cat, req_cat} <= {"SE", "SENIOR", "SENIORS"}
            )
            if not is_cat_match:
                # Vérifier aussi dans le nom de l'équipe
                c_nom = (c.get("nom") or c.get("team_label") or "").upper().strip()
                if req_cat not in c_nom:
                    continue
            if req_sexe and c_sexe and req_sexe != c_sexe:
                continue
            cat_candidates.append(c)

        candidates = cat_candidates

    elif categorie and has_category_metadata:
        # Une catégorie a été explicitement demandée mais n'est ni une division reconnue
        # ni une catégorie d'âge/sexe identifiable
        strategies.append("unknown_category")
        all_labels = sorted(
            [str(t["team_label"]) for t in all_teams if t.get("team_label")]
        )
        return TeamResolutionResult(
            status=ResponseStatus.NOT_FOUND,
            club_resolu=club_resolu,
            candidates=[{"label": lbl} for lbl in all_labels],
            ambiguity_message=f"Catégorie ou division '{categorie}' inconnue. Aucun rapprochement silencieux possible.",
            match_strategy=strategies,
        )

    # -----------------------------------------------------------------------
    # Numéro d'équipe
    # -----------------------------------------------------------------------
    eff_num = numero_equipe
    if eff_num is None and parsed_req and parsed_req.numero_equipe is not None:
        eff_num = parsed_req.numero_equipe

    if eff_num is not None:
        strategies.append(f"filter_team_number_{eff_num}")
        num_str = str(eff_num)

        def _cand_nom(c: dict[str, Any]) -> str:
            return str(c.get("nom_equipe") or c.get("nom") or "")

        exact_num = [
            c
            for c in candidates
            if str(c.get("numero_equipe") or "").strip() == num_str
            or _cand_nom(c).endswith(f"- {num_str}")
            or _cand_nom(c).endswith(f"-{num_str}")
        ]
        if exact_num:
            candidates = exact_num
        elif eff_num is not None and eff_num >= 1:
            # Équipe n°N demandée sans numéro explicite FFBB : filtrer les équipes
            # qui ne portent pas explicitement un autre numéro
            potential_teams = [
                c
                for c in candidates
                if str(c.get("numero_equipe") or "").strip() in ("", str(eff_num))
                and not any(
                    _cand_nom(c).endswith(f"- {n}") or _cand_nom(c).endswith(f"-{n}")
                    for n in range(1, 10)
                    if n != eff_num
                )
            ]
            from ffbb_mcp.services.division import resolve_team_by_division_rank

            if len(potential_teams) == 1:
                # Cas historique : une seule équipe sans numéro explicite.
                potential_teams[0].setdefault(
                    "note",
                    "équipe sans numéro explicite, correspond potentiellement à ce numéro",
                )
                candidates = potential_teams
            else:
                chosen, tied = resolve_team_by_division_rank(potential_teams, eff_num)
                if chosen is not None:
                    if eff_num == 1:
                        strategies.append("fallback_highest_division_as_team_1")
                        note = "équipe fanion (équipe 1) résolue par hiérarchie de niveau de compétition"
                    else:
                        strategies.append(
                            f"fallback_division_hierarchy_as_team_{eff_num}"
                        )
                        note = f"équipe réserve (équipe {eff_num}) résolue par hiérarchie de niveau de compétition"
                    chosen.setdefault("note", note)
                    candidates = [chosen]
                elif tied:
                    candidates = tied
                else:
                    candidates = []
        else:
            candidates = []

    # Dédupliquer les phases successives
    candidates = _dedup_same_team_phases(candidates)

    # -----------------------------------------------------------------------
    # ÉVALUATION FINALE SELON LE MODE
    # -----------------------------------------------------------------------
    if mode == "all":
        return TeamResolutionResult(
            status=ResponseStatus.OK if candidates else ResponseStatus.NOT_FOUND,
            candidates=candidates,
            club_resolu=club_resolu,
            match_strategy=strategies,
        )

    if not candidates:
        all_labels = sorted(
            [str(t["team_label"]) for t in all_teams if t.get("team_label")]
        )
        return TeamResolutionResult(
            status=ResponseStatus.NOT_FOUND,
            club_resolu=club_resolu,
            candidates=[{"label": lbl} for lbl in all_labels],
            ambiguity_message=f"Aucune équipe trouvée correspondant aux critères spécifiés pour '{categorie or club_name}'.",
            match_strategy=strategies,
        )

    if len(candidates) == 1:
        return TeamResolutionResult(
            status=ResponseStatus.OK,
            selected=candidates[0],
            candidates=candidates,
            club_resolu=club_resolu,
            match_strategy=strategies,
            confidence=1.0,
        )

    # Plusieurs candidats subsistent -> ambiguïté réelle
    user_choices = []
    for c in candidates:
        team_lbl = (
            c.get("team_label")
            or c.get("nom")
            or c.get("nom_equipe")
            or categorie
            or "Équipe"
        )
        num = c.get("numero_equipe")
        comp = c.get("competition") or c.get("competition_name") or ""
        parts = []
        if num and num not in (1, "1") and str(num) not in team_lbl:
            parts.append(f"{team_lbl} {num}")
        else:
            parts.append(team_lbl)
        if comp:
            parts.append(comp)
        user_choices.append(" — ".join(parts))

    club_disp = club_resolu.get("nom") if club_resolu else (club_name or "ce club")
    prompt = (
        f"L'équipe {club_disp} a {len(candidates)} engagements distincts : "
        + " ; ".join(user_choices)
        + ". Précisez la division, la catégorie ou le numéro d'équipe."
    )

    amb_msg = (
        f"Plusieurs engagements ({len(candidates)}) existent pour ce club. Veuillez préciser la catégorie ou l'engagement recherché."
        if not categorie
        else f"Plusieurs engagements ({len(candidates)}) correspondent à cette recherche."
    )

    return TeamResolutionResult(
        status=ResponseStatus.AMBIGUOUS,
        selected=None,
        candidates=candidates,
        club_resolu=club_resolu,
        ambiguity_message=amb_msg,
        clarification_prompt=prompt,
        match_strategy=strategies,
        confidence=0.5,
    )
