"""Service de résolution d'équipes et de recherche d'équipes candidates.

Isole la logique métier de désambiguïsation d'équipes (fanion vs réserve,
coupe vs championnat, hiérarchie de division et prochain match programmé)
initialement contenue dans services/search.py.
"""

from __future__ import annotations

import logging
import re
import sys
import zoneinfo
from datetime import datetime
from typing import Any

from ffbb_mcp.competition_type import resolve_competition_type
from ffbb_mcp.envelope import ResponseStatus
from ffbb_mcp.presentation import (
    build_ambiguous_presentation,
    build_provenance_block,
    format_source_label,
)
from ffbb_mcp.services.common import (
    _ELIMINATION_KEYWORDS,
    INTERNAL_ERROR,
    ErrorData,
    McpError,
    _extract_phase_num,
    _normalize_name,
    disambiguate_clubs_by_category,
    get_primary_club,
    is_real_ambiguity,
)
from ffbb_mcp.services.division import get_competition_level_rank
from ffbb_mcp.utils import parse_categorie

logger = logging.getLogger("ffbb-mcp")

_paris_tz = zoneinfo.ZoneInfo("Europe/Paris")

_PHASE_PATTERN = re.compile(
    r"\s*[-–]\s*(phase\s*\d+|1/\d+\s*finales?|demi[- ]finales?|quarts?|finales?|poules?|brassage|plateaux?)\b.*",  # noqa: RUF001
    re.IGNORECASE,
)


def _get_search_service(name: str, fallback: Any) -> Any:
    """Résout dynamiquement un service depuis search ou services pour compatibilité des mocks."""
    mod = sys.modules.get("ffbb_mcp.services.search")
    if mod and hasattr(mod, name):
        return getattr(mod, name)
    mod_svc = sys.modules.get("ffbb_mcp.services")
    if mod_svc and hasattr(mod_svc, name):
        return getattr(mod_svc, name)
    return fallback


def _phase_sort_key(e: dict) -> tuple[int, int, int]:
    """Clé de tri pour sélectionner la phase la plus avancée.

    Priorité :
    1. Phase éliminatoire > phase de poule
    2. Numéro de phase le plus élevé
    3. Niveau le plus élevé
    """
    competition = e.get("competition") or ""
    is_elimination = 1 if _ELIMINATION_KEYWORDS.search(competition) else 0
    phase_num = _extract_phase_num(e.get("phase_label") or competition)
    niveau = e.get("niveau") or 0
    return (is_elimination, phase_num, niveau)


def _extract_base_competition_name(comp_name: str) -> str:
    if not comp_name:
        return ""

    if "-" not in comp_name and "–" not in comp_name:  # noqa: RUF001
        return _normalize_name(comp_name.strip())

    base = _PHASE_PATTERN.sub("", comp_name).strip()
    return _normalize_name(base)


def _is_coupe_competition(comp_name: str, comp_type: str | None) -> bool:
    if comp_type and comp_type.upper() == "COUPE":
        return True
    norm = _normalize_name(comp_name)
    return (
        "COUPE" in norm or "CHALLENGE" in norm or "TROFEE" in norm or "TROPHEE" in norm
    )


def _deduplicate_same_team_phases(candidates: list[dict]) -> list[dict]:
    """Déduplique les candidats qui sont la même équipe au sein de la MÊME compétition (phases successives).

    Ne déduplique JAMAIS si les candidats appartiennent à des compétitions ou types de compétition distincts
    (ex: Championnat vs Coupe ARA), ni si un même nom d'équipe sans suffixe couvre
    deux divisions de niveaux différents (ex: RMU15 Brassage régional vs
    Départementale U15 — fanion vs réserve).
    """
    if len(candidates) <= 1:
        return candidates

    # 1) Regrouper par (team_name, numero) — même équipe présumée.
    first_groups: dict[tuple[str, str], list[dict]] = {}
    for c in candidates:
        team_name = _normalize_name(
            c.get("nom_equipe") or c.get("nom") or c.get("team_label") or ""
        )
        numero = str(c.get("numero_equipe") or "").strip()
        first_groups.setdefault((team_name, numero), []).append(c)

    deduped: list[dict] = []
    for (_team, _num), group in first_groups.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue

        # 2) Partition par is_coupe : championnat vs coupe ne fusionnent jamais.
        coupe_groups: dict[bool, list[dict]] = {}
        for c in group:
            comp_name = c.get("competition") or c.get("competition_code") or ""
            is_coupe = _is_coupe_competition(comp_name, c.get("competition_type"))
            coupe_groups.setdefault(is_coupe, []).append(c)

        for _is_coupe, cg in coupe_groups.items():
            if len(cg) == 1:
                deduped.append(cg[0])
                continue
            # 3) Familles de niveau confiantes (rank >= 1000 : National/Régional/Départemental).
            # Un rang < 1000 (fallback générique, métadonnées minimales des vieux tests)
            # est un joker : il ne crée pas une nouvelle famille à lui seul.
            families: dict[int, list[dict]] = {}
            for c in cg:
                try:
                    rank = get_competition_level_rank(c)
                except Exception:
                    rank = 0
                fam = rank // 1000 if rank >= 1000 else 0
                families.setdefault(fam, []).append(c)
            confident_fams = sorted(f for f in families if f >= 1)
            if len(confident_fams) <= 1:
                # Même famille (ou jokers uniquement) → phases successives : garder la meilleure.
                best = max(cg, key=_phase_sort_key)
                deduped.append(best)
            else:
                # Plusieurs niveaux réels distincts (ex: régional vs départemental) →
                # équipes distinctes (fanion vs réserve) : garder la meilleure par niveau,
                # niveau le plus élevé en premier (cohérent avec find_team_candidates).
                for _fam, members in sorted(families.items(), reverse=True):
                    best = max(members, key=_phase_sort_key)
                    deduped.append(best)

    return deduped


def _determine_niveau_label(comp_name: str, comp_type: str, raw_niveau: Any) -> str:
    """Détermine un niveau lisible pour les humains et les LLMs."""
    upper = (comp_name or "").upper()
    if "BRASSAGE" in upper and any(
        k in upper
        for k in (
            "RF",
            "RM",
            "RÉGION",
            "REGION",
            "REGIONAL",
            "R1",
            "R2",
            "R3",
        )
    ):
        return "régional / brassage"
    if any(
        k in upper
        for k in (
            "RF",
            "RM",
            "R1",
            "R2",
            "R3",
            "PNM",
            "PNF",
            "RÉGION",
            "REGION",
            "REGIONAL",
        )
    ):
        return "régional"
    if any(k in upper for k in ("NM", "NF", "NATIONALE", "NATIONAL", "N1", "N2", "N3")):
        return "national"
    if any(
        k in upper
        for k in ("DÉPARTEMENTAL", "DEPARTEMENTAL", "DF", "DM", "D1", "D2", "D3")
    ):
        return "départemental"
    if "COUPE" in upper or (comp_type or "").upper() == "COUPE":
        return "coupe"
    if raw_niveau == 1:
        return "régional"
    if raw_niveau == 2:
        return "départemental"
    return "départemental"


def _dump_resolution_without_candidates(res: Any) -> dict[str, Any]:
    """Extrait le dump de la résolution en éliminant 'candidates' pour éviter la duplication."""
    if not hasattr(res, "model_dump") or not callable(res.model_dump):
        return {}
    try:
        dumped = res.model_dump(exclude={"candidates"})
    except TypeError:
        dumped = res.model_dump()
    if isinstance(dumped, dict):
        return {k: v for k, v in dumped.items() if k != "candidates"}
    return {}


async def ffbb_resolve_team_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    numero_equipe: int | str | None = None,
    engagement_id: int | str | None = None,
    competition_id: int | str | None = None,
    competition_type: str | None = None,
    poule_id: int | str | None = None,
    season_id: int | str | None = None,
    force_refresh: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Résout une équipe unique d'un club pour une catégorie donnée via resolve_team_strict.

    Retourne un objet structuré et déterministe pour les agents :
      - `status`: "resolved" | "ambiguous" | "not_found"
      - `team`: engagement résolu (ou None si ambigu / introuvable)
      - `candidates`: liste des engagements candidats
      - `ambiguity`: message explicite en cas d'ambiguïté
      - `clarification_prompt`: question exploitable par le LLM pour clarifier
    """
    if not club_name and not organisme_id and not engagement_id:
        raise McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message="Fournir club_name ou organisme_id (ou engagement_id)",
            )
        )

    int_num: int | None = None
    if numero_equipe is not None:
        try:
            int_num = int(numero_equipe)
        except (ValueError, TypeError):
            int_num = None

    import ffbb_mcp.strict_resolver

    mode = kwargs.get("mode", "suggest")
    res = await ffbb_mcp.strict_resolver.resolve_team_strict(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        numero_equipe=int_num,
        engagement_id=engagement_id,
        competition_id=competition_id,
        competition_type=competition_type,
        poule_id=poule_id,
        season_id=season_id,
        mode=mode,
        force_refresh=force_refresh,
        **kwargs,
    )

    if res.status == ResponseStatus.OK:
        sel_team = res.selected if isinstance(res.selected, dict) else {}
        comp_name = sel_team.get("competition") or ""
        lbl = (
            sel_team.get("team_label")
            or sel_team.get("nom_equipe")
            or categorie
            or "Équipe"
        )
        res_ids = {
            "engagement_id": str(sel_team.get("engagement_id"))
            if sel_team.get("engagement_id")
            else None,
            "poule_id": str(sel_team.get("poule_id"))
            if sel_team.get("poule_id")
            else None,
            "competition_id": str(sel_team.get("competition_id"))
            if sel_team.get("competition_id")
            else None,
        }
        provenance = build_provenance_block(
            source="ffbb_api_live",
            cache_status="hit" if not force_refresh else "miss",
            resource_ids=res_ids,
        )
        presentation = {
            "short_answer": f"Équipe résolue : {lbl}.",
            "detail_line": f"Engagée en {comp_name}."
            if comp_name
            else "Engagement confirmé.",
            "source_label": format_source_label(),
            "warnings": [],
        }
        return {
            "status": "resolved",
            "team": res.selected,
            "candidates": res.candidates,
            "ambiguity": None,
            "clarification_prompt": None,
            "club_resolu": res.club_resolu,
            "presentation": presentation,
            "provenance": provenance,
            "resolution": _dump_resolution_without_candidates(res),
        }
    elif res.status == ResponseStatus.AMBIGUOUS:
        ambig_block = build_ambiguous_presentation(
            candidates=res.candidates,
            club_name=(
                res.club_resolu.get("nom")
                if isinstance(res.club_resolu, dict)
                else club_name
            ),
            categorie=categorie,
        )
        return {
            "status": "ambiguous",
            "team": None,
            "candidates": res.candidates,
            "ambiguity": res.ambiguity_message,
            "clarification_prompt": ambig_block["clarification_prompt"],
            "club_resolu": res.club_resolu,
            "presentation": ambig_block["presentation"],
            "provenance": ambig_block["provenance"],
            "resolution": _dump_resolution_without_candidates(res),
        }
    else:
        provenance = build_provenance_block(
            source="ffbb_api_live",
            cache_status="hit" if not force_refresh else "miss",
        )
        presentation = {
            "short_answer": f"Aucune équipe trouvée pour '{categorie or club_name}'.",
            "detail_line": res.ambiguity_message
            or "Vérifiez l'orthographe ou les critères demandés.",
            "source_label": format_source_label(),
            "warnings": [res.ambiguity_message] if res.ambiguity_message else [],
        }
        return {
            "status": "not_found",
            "team": None,
            "candidates": res.candidates,
            "ambiguity": res.ambiguity_message,
            "clarification_prompt": res.clarification_prompt,
            "club_resolu": res.club_resolu,
            "presentation": presentation,
            "provenance": provenance,
            "resolution": _dump_resolution_without_candidates(res),
        }


async def ffbb_find_team_candidates_service(
    club_name: str | None = None,
    organisme_id: int | str | None = None,
    categorie: str | None = None,
    sexe: str | None = None,
    numero_equipe: int | str | None = None,
    season_id: int | str | None = None,
    force_refresh: bool = False,
    include_next_match: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Recherche et ordonne les équipes candidates d'un club/CTC pour désambiguïser avant tout calendrier/résultat.

    Évite la confusion entre équipe fanion sans numéro (ex: U13F en régional) et équipe réserve (ex: U13F2 en départemental).
    Retourne la liste des candidats triés avec confiance, motif, détails de compétition et prochain match.
    """
    import ffbb_mcp.services
    from ffbb_mcp.aliases_registry import get_aliases_registry

    if not club_name and not organisme_id:
        raise McpError(
            error=ErrorData(
                code=INTERNAL_ERROR,
                message="Fournir au minimum club_name ou organisme_id",
            )
        )

    _res_club = _get_search_service(
        "resolve_club_and_org", getattr(ffbb_mcp.services, "resolve_club_and_org", None)
    )
    resolved_clubs, _ = await _res_club(
        club_name=club_name,
        organisme_id=organisme_id,
        categorie=categorie,
        force_refresh=force_refresh,
    )
    if not resolved_clubs:
        return {
            "status": "not_found",
            "message": f"Club '{club_name or organisme_id}' introuvable.",
            "candidates": [],
            "clarification_prompt": None,
        }

    if not organisme_id and categorie:
        resolved_clubs, _ = await disambiguate_clubs_by_category(
            resolved_clubs,
            categorie=categorie,
            club_name=club_name,
            season_id=season_id,
            force_refresh=force_refresh,
        )

    if is_real_ambiguity(resolved_clubs, club_name) and not organisme_id:
        return {
            "status": "ambiguous_club",
            "message": f"Plusieurs clubs correspondent à '{club_name}'. Précisez l'organisme_id.",
            "candidates": resolved_clubs,
            "clarification_prompt": f"Plusieurs clubs correspondent à '{club_name}'. Précisez l'organisme_id parmi les options.",
        }

    club_resolu = get_primary_club(resolved_clubs, club_name) or resolved_clubs[0]
    target_org_id = str(club_resolu["organisme_id"])
    club_nom = club_resolu.get("nom", "")

    _eq_svc = _get_search_service(
        "ffbb_equipes_club_service", ffbb_mcp.services.ffbb_equipes_club_service
    )
    all_teams = await _eq_svc(
        organisme_id=target_org_id,
        force_refresh=force_refresh,
        season_id=season_id,
    )
    if not all_teams or (len(all_teams) == 1 and "error" in all_teams[0]):
        return {
            "status": "not_found",
            "message": f"Aucune équipe engagée trouvée pour le club '{club_nom}'.",
            "club": club_resolu,
            "candidates": [],
            "clarification_prompt": None,
        }

    registry = get_aliases_registry()
    parsed_req = parse_categorie(categorie) if categorie else None
    target_div = registry.lookup(categorie) if categorie else None

    req_age: str | None = None
    req_sexe: str | None = sexe.upper().strip() if sexe else None
    req_num: int | None = None

    if numero_equipe is not None:
        try:
            req_num = int(numero_equipe)
        except (ValueError, TypeError):
            req_num = None
    elif parsed_req and parsed_req.numero_equipe is not None:
        req_num = parsed_req.numero_equipe

    if parsed_req and parsed_req.categorie:
        req_age = parsed_req.categorie.upper().strip()
    if not req_sexe and parsed_req and parsed_req.sexe:
        req_sexe = parsed_req.sexe.upper().strip()

    if target_div:
        if target_div.canonical_age:
            req_age = target_div.canonical_age
        if not req_sexe and target_div.sex:
            req_sexe = target_div.sex

    matching_teams: list[dict[str, Any]] = []
    for t in all_teams:
        if not isinstance(t, dict) or "error" in t:
            continue
        t_cat = (t.get("categorie") or "").upper().strip()
        t_sexe = (t.get("sexe") or "").upper().strip()
        t_label = (t.get("team_label") or "").upper().strip()
        t_comp = (t.get("competition") or "").upper().strip()

        # 1. Tranche d'âge
        if req_age:
            is_age_match = (
                t_cat == req_age
                or {t_cat, req_age} <= {"SE", "SENIOR", "SENIORS"}
                or req_age in t_label
                or req_age in t_comp
            )
            if not is_age_match:
                continue

        # 2. Genre
        if req_sexe:
            if t_sexe and t_sexe != req_sexe:
                continue
            if not t_sexe:
                if req_sexe == "F" and "F" not in t_label and "FEMININ" not in t_comp:
                    continue
                if req_sexe == "M" and "M" not in t_label and "MASCULIN" not in t_comp:
                    continue

        matching_teams.append(t)

    if not matching_teams and (req_age or req_sexe):
        return {
            "status": "not_found",
            "message": f"Aucune équipe trouvée pour le club '{club_nom}' avec les critères spécifiés (catégorie={categorie}, sexe={sexe}).",
            "club": club_resolu,
            "candidates": [],
            "clarification_prompt": None,
        }

    if not matching_teams:
        matching_teams = [
            t for t in all_teams if isinstance(t, dict) and "error" not in t
        ]

    # Déduplication par engagement_id
    seen_engs: set[str] = set()
    unique_teams: list[dict[str, Any]] = []
    for t in matching_teams:
        eid = str(t.get("engagement_id") or t.get("team_id") or "")
        if eid and eid in seen_engs:
            continue
        if eid:
            seen_engs.add(eid)
        unique_teams.append(t)

    max_div_rank_per_label: dict[str, int] = {}
    for t in unique_teams:
        lbl = str(t.get("team_label") or "").upper().strip()
        r = get_competition_level_rank(t)
        if r > max_div_rank_per_label.get(lbl, -1):
            max_div_rank_per_label[lbl] = r

    candidates: list[dict[str, Any]] = []
    for t in unique_teams:
        team_label = t.get("team_label") or ""
        numero_raw = t.get("numero_equipe")
        cand_num = (
            int(numero_raw) if (numero_raw and str(numero_raw).isdigit()) else None
        )
        comp_name = (t.get("competition") or "").strip()
        comp_type = (t.get("competition_type") or "").strip()
        raw_niveau = t.get("niveau")
        niveau_str = _determine_niveau_label(comp_name, comp_type, raw_niveau)
        eng_id = str(t.get("engagement_id") or t.get("team_id") or "")
        poule_id = str(t.get("poule_id") or "") if t.get("poule_id") else None

        nom_officiel = t.get("nom_equipe") or club_nom
        next_match_info: dict[str, Any] | None = None

        if include_next_match and poule_id:
            try:
                _matches_svc = _get_search_service(
                    "_fetch_poule_matches", ffbb_mcp.services._fetch_poule_matches
                )
                matches = await _matches_svc(
                    [t],
                    organisme_nom=club_nom,
                    numero_equipe=cand_num,
                    force_refresh=force_refresh,
                )
                if matches:
                    for m, _ in matches:
                        m_nom1 = str(m.get("nomEquipe1") or "")
                        m_nom2 = str(m.get("nomEquipe2") or "")
                        for cand_nom in (m_nom1, m_nom2):
                            cand_nom_clean = cand_nom.strip()
                            if (
                                club_nom.lower() in cand_nom_clean.lower()
                                or "ctc" in cand_nom_clean.lower()
                                or "entente" in cand_nom_clean.lower()
                            ):
                                if cand_num is None or cand_num == 1:
                                    if not any(
                                        cand_nom_clean.endswith(f"- {n}")
                                        for n in range(2, 10)
                                    ):
                                        nom_officiel = cand_nom_clean
                                        break
                                elif cand_nom_clean.endswith(
                                    f"- {cand_num}"
                                ) or cand_nom_clean.endswith(f"-{cand_num}"):
                                    nom_officiel = cand_nom_clean
                                    break
                        if nom_officiel != (t.get("nom_equipe") or club_nom):
                            break

                    def _match_sort_key(item: tuple[dict, dict]) -> str:
                        m = item[0]
                        d = m.get("date_rencontre") or m.get("date") or "9999-99-99"
                        h = m.get("heure") or "00:00"
                        return f"{d} {h}"

                    sorted_matches = sorted(matches, key=_match_sort_key)
                    today_iso = datetime.now(_paris_tz).strftime("%Y-%m-%d")
                    upcoming = [
                        m
                        for m, _ in sorted_matches
                        if (m.get("date_rencontre") or m.get("date") or "") >= today_iso
                    ]
                    target_m = (
                        upcoming[0]
                        if upcoming
                        else (sorted_matches[-1][0] if sorted_matches else None)
                    )

                    if target_m:
                        m1 = target_m.get("nomEquipe1") or ""
                        m2 = target_m.get("nomEquipe2") or ""
                        is_dom = (
                            nom_officiel.lower() in m1.lower()
                            or club_nom.lower() in m1.lower()
                        )
                        adv = m2 if is_dom else m1
                        date_m = str(
                            target_m.get("date_rencontre") or target_m.get("date") or ""
                        )
                        heure_raw = target_m.get("heure")
                        horaire_flag = target_m.get("horaire")
                        heure_str_raw = str(heure_raw or "").strip()
                        if horaire_flag in ("0", 0) or heure_str_raw[:5] in (
                            "00:00",
                            "00h00",
                            "0",
                        ):
                            heure_str = "Horaire à fixer"
                        elif heure_raw:
                            heure_str = heure_str_raw[:5].replace(":", "h")
                        elif len(date_m) >= 16 and " " in date_m:
                            time_part = date_m.split()[1][:5]
                            if time_part in ("00:00", "00h00"):
                                heure_str = "Horaire à fixer"
                            else:
                                heure_str = time_part.replace(":", "h")
                        else:
                            heure_str = "Horaire à fixer"
                        if heure_str in ("00h00", "00:00"):
                            heure_str = "Horaire à fixer"

                        next_match_info = {
                            "date": date_m[:10] if date_m else "Date non fixée",
                            "heure": heure_str,
                            "adversaire": adv,
                            "domicile_exterieur": (
                                "domicile" if is_dom else "extérieur"
                            ),
                            "lieu": (
                                target_m.get("nomSalle")
                                or (
                                    target_m.get("commune", {}).get("nom")
                                    if isinstance(target_m.get("commune"), dict)
                                    else target_m.get("commune")
                                )
                                or None
                            ),
                        }
            except Exception as e:
                logger.debug(
                    "Erreur récupération next_match candidat %s: %s", eng_id, e
                )

        # Calcul confiance & motif
        confidence = 0.5
        reason = ""

        cand_div_rank = get_competition_level_rank(t)

        if req_num is not None:
            if cand_num == req_num:
                confidence = 1.0
                reason = f"Correspondance exacte : équipe n°{cand_num} ({team_label}, {comp_name})."
            elif cand_num is None:
                if req_num == 1:
                    none_ranks = [
                        get_competition_level_rank(tm)
                        for tm in unique_teams
                        if not tm.get("numero_equipe")
                    ]
                    max_none_rank = max(none_ranks) if none_ranks else 0
                    is_unique_max = none_ranks.count(max_none_rank) == 1
                    if (
                        cand_div_rank == max_none_rank
                        and is_unique_max
                        and len(none_ranks) > 1
                    ):
                        confidence = 0.95
                        reason = (
                            f"Équipe fanion sans numéro explicite résolue par hiérarchie de niveau "
                            f"({team_label}, {comp_name}, niveau {niveau_str})."
                        )
                    elif cand_div_rank < max_none_rank:
                        confidence = 0.55
                        reason = (
                            f"Équipe de niveau inférieur ({team_label}, {comp_name}, niveau {niveau_str}) "
                            f"alors que l'équipe fanion n°1 était requise."
                        )
                    else:
                        confidence = 0.85
                        reason = (
                            f"Équipe principale sans numéro explicite dans FFBB ({team_label}, {comp_name}, niveau {niveau_str}). "
                            "En FFBB, l'équipe fanion / de plus haut niveau n'a généralement pas de suffixe '1'."
                        )
                else:
                    confidence = 0.40
                    reason = f"Équipe sans numéro explicite ({team_label}) alors que l'équipe n°{req_num} était requise."
            else:
                confidence = 0.60 if abs(cand_num - req_num) == 1 else 0.45
                reason = (
                    f"Même catégorie ({team_label}), mais équipe distincte n°{cand_num} "
                    f"engagée en {comp_name} (niveau {niveau_str})."
                )
        elif categorie and team_label.upper() == categorie.upper().strip():
            if cand_div_rank < max_div_rank_per_label.get(
                team_label.upper().strip(), 0
            ):
                confidence = 0.65
                reason = (
                    f"Libellé FFBB '{team_label}' ({comp_name}), "
                    f"mais division inférieure ({niveau_str}) par rapport à l'équipe fanion."
                )
            else:
                confidence = 0.95
                reason = f"Libellé FFBB exact '{team_label}' ({comp_name})."
        elif cand_num == 1 or cand_num is None:
            if cand_div_rank < max_div_rank_per_label.get(
                team_label.upper().strip(), 0
            ):
                confidence = 0.65
                reason = (
                    f"Équipe sans numéro explicite ({team_label}, {comp_name}), "
                    f"mais division inférieure ({niveau_str}) par rapport à l'équipe fanion."
                )
            else:
                confidence = 0.85
                reason = f"Équipe fanion / principale ({team_label}, {comp_name}, niveau {niveau_str})."
        else:
            confidence = 0.70
            reason = f"Équipe réserve n°{cand_num} ({team_label}, {comp_name}, niveau {niveau_str})."

        comp_type_detail = resolve_competition_type(comp_type)
        candidates.append(
            {
                "nom_equipe": nom_officiel,
                "team_label": team_label,
                "numero_equipe": cand_num,
                "competition_name": comp_name,
                "competition_type": comp_type,
                "competition_type_code": comp_type,
                "competition_type_detail": comp_type_detail.model_dump(),
                "niveau": niveau_str,
                "div_rank": cand_div_rank,
                "engagement_id": eng_id,
                "poule_id": poule_id,
                "next_match": next_match_info,
                "confidence": confidence,
                "match_confidence": confidence,
                "match_reason": reason,
            }
        )

    # Tri par score décroissant puis niveau de compétition
    def _cand_sort_key(c: dict[str, Any]) -> tuple[float, int, int, int]:
        conf = c["match_confidence"]
        d_rank = c.get("div_rank", 0)
        num_score = 10 if c["numero_equipe"] in (1, None) else 5
        niv_score = 10 if "régional" in c["niveau"] or "national" in c["niveau"] else 5
        return (conf, d_rank, num_score, niv_score)

    candidates.sort(key=_cand_sort_key, reverse=True)

    if not candidates:
        from ffbb_mcp.presentation import format_source_label

        return {
            "status": "not_found",
            "club": club_resolu,
            "candidates": [],
            "ambiguity": f"Aucun engagement ne correspond aux critères spécifiés ({categorie}).",
            "clarification_prompt": None,
            "presentation": {
                "short_answer": f"Aucune équipe candidate trouvée pour {club_nom} ({categorie or ''}).".strip(),
                "detail_line": "Vérifiez l'orthographe du club ou la catégorie demandée.",
                "source_label": format_source_label(),
                "warnings": [
                    f"Aucun engagement ne correspond aux critères ({categorie})."
                ],
            },
        }

    status = "ambiguous"
    if len(candidates) == 1 or (
        req_num is not None
        and candidates[0]["match_confidence"] == 1.0
        and candidates[1]["match_confidence"] < 0.7
    ):
        status = "resolved"

    clarification_prompt = None
    if status == "ambiguous" or len(candidates) > 1:
        lines = [
            "## Équipes candidates\n",
            f"Je ne trouve pas de libellé FFBB exact correspondant à `{categorie or 'votre recherche'}`.",
            f"Voici les équipes les plus proches pour {club_nom} :\n",
        ]
        for idx, c in enumerate(candidates, 1):
            num_str = (
                f"{c['numero_equipe']}"
                if c.get("numero_equipe") is not None
                else "non renseigné dans FFBB"
            )
            nxt = c.get("next_match")
            if nxt:
                nxt_str = f"{nxt.get('date')} à {nxt.get('heure')}, vs {nxt.get('adversaire')} ({nxt.get('domicile_exterieur')})"
            else:
                nxt_str = "non disponible"

            lines.append(
                f"{idx}. **{c['nom_equipe']}**\n"
                f"   - Étiquette FFBB : `{c['team_label']}`\n"
                f"   - Compétition : `{c['competition_name']}`\n"
                f"   - Niveau : `{c['niveau']}`\n"
                f"   - Numéro d'équipe : `{num_str}`\n"
                f"   - Engagement : `{c['engagement_id']}`\n"
                f"   - Prochain match : {nxt_str}\n"
            )

        lines.append(
            "> Laquelle souhaites-tu consulter ? Réponds avec le numéro ou avec l'engagement_id."
        )
        clarification_prompt = "\n".join(lines)

    from ffbb_mcp.presentation import format_source_label

    short_ans = f"{len(candidates)} équipe(s) candidate(s) trouvée(s) pour {club_nom}."
    detail = (
        f"Meilleure correspondance : {candidates[0]['nom_equipe']} ({candidates[0]['competition_name']})."
        if candidates
        else ""
    )
    presentation = {
        "short_answer": short_ans,
        "detail_line": detail,
        "source_label": format_source_label(),
        "warnings": [],
    }

    return {
        "status": status,
        "club": club_resolu,
        "total_candidates": len(candidates),
        "candidates": candidates,
        "clarification_prompt": clarification_prompt,
        "presentation": presentation,
    }
