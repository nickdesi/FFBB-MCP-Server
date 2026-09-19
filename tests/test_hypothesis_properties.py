"""Tests property-based avec Hypothesis pour certifier les propriétés fondamentales du serveur FFBB MCP."""

from __future__ import annotations

import unicodedata

from hypothesis import given, settings
from hypothesis import strategies as st

from ffbb_mcp.aliases_registry import get_aliases_registry
from ffbb_mcp.canonical_status import CanonicalMatchStatus, canonicalize_match_status

# Stratégie générant des divisions arbitraires ou mal formées
divisions_strategy = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=1,
    max_size=30,
)

# Statuts bruts possibles
raw_statuts_strategy = st.sampled_from(
    [
        "scheduled",
        "in_progress",
        "complete",
        "live",
        "final",
        "official",
        "postponed",
        "cancelled",
        "forfeit",
        None,
        "",
        "unknown",
    ]
)

scores_strategy = st.one_of(st.none(), st.integers(min_value=-10, max_value=200))


@given(raw_query=st.text(min_size=1, max_size=20))
@settings(max_examples=100)
def test_property_no_random_string_maps_to_national_division_unless_declared(
    raw_query: str,
):
    """Propriété : Aucune chaîne aléatoire ne peut résoudre une division nationale si non déclarée."""
    registry = get_aliases_registry()
    div = registry.lookup(raw_query)
    if div is not None:
        # Si une division a été trouvée, la chaîne nettoyée doit être dans ses alias
        norm = registry.normalize_alias(raw_query)
        assert norm in div.aliases


@given(
    played=st.booleans(),
    statut=st.sampled_from(
        ["scheduled", "final", "live", "cancelled", "postponed", None]
    ),
    current_status=st.sampled_from(["complete", "live", "scheduled", None]),
    match_status=st.sampled_from(["IN_PROGRESS", "FINAL", "SCHEDULED", None]),
    score1=scores_strategy,
    score2=scores_strategy,
)
@settings(max_examples=150)
def test_property_contradictory_match_is_never_silently_ok(
    played: bool,
    statut: str | None,
    current_status: str | None,
    match_status: str | None,
    score1: int | None,
    score2: int | None,
):
    """Propriété critique : Tout match ayant des statuts contradictoires est obligatoirement marqué UNKNOWN_CONFLICT."""
    raw_match = {
        "played": played,
        "statut": statut,
        "current_status": current_status,
        "match_status": match_status,
        "score_equipe1": score1,
        "score_equipe2": score2,
    }

    canon_status, quality = canonicalize_match_status(raw_match)

    # Incohérence flagrante : match joué ou avec score mais statut scheduled
    is_played_scheduled = played and (
        statut == "scheduled" or match_status == "SCHEDULED"
    )
    is_complete_live = current_status == "complete" and match_status == "IN_PROGRESS"
    is_has_scores_scheduled = (
        score1 is not None
        and score2 is not None
        and score1 >= 0
        and score2 >= 0
        and (statut == "scheduled" or match_status == "SCHEDULED")
    )

    if is_played_scheduled or is_complete_live or is_has_scores_scheduled:
        assert canon_status == CanonicalMatchStatus.UNKNOWN_CONFLICT
        assert quality.level == "conflict"
        assert len(quality.issues) > 0


@given(
    alias=st.sampled_from(
        ["NM1", "NM2", "NM3", "PNM", "RM1", "RM2", "ELIT2", "U15M", "U15F"]
    )
)
@settings(max_examples=50)
def test_property_unicode_forms_do_not_alter_canonical_semantics(alias: str):
    """Propriété : Toutes les formes de normalisation Unicode (NFC, NFD, NFKC, NFKD) préservent la sémantique."""
    registry = get_aliases_registry()
    div_base = registry.lookup(alias)
    assert div_base is not None

    for form in ("NFC", "NFD", "NFKC", "NFKD"):
        normalized_str = unicodedata.normalize(form, alias)
        div_norm = registry.lookup(normalized_str)
        assert div_norm is not None
        assert div_norm.canonical_code == div_base.canonical_code


@given(
    cat_national=st.sampled_from(["NM1", "NM2", "NM3", "LF2", "NF1", "NF2", "NF3"]),
    cat_regional=st.sampled_from(
        ["PNM", "RM1", "RM2", "RM3", "PNF", "RF1", "RF2", "PRM"]
    ),
)
@settings(max_examples=100)
def test_property_national_and_regional_are_strictly_disjoint(
    cat_national: str, cat_regional: str
):
    """Propriété fondamentale : Les divisions nationales et régionales sont strictement disjointes."""
    registry = get_aliases_registry()
    div_nat = registry.lookup(cat_national)
    div_reg = registry.lookup(cat_regional)

    assert div_nat is not None
    assert div_reg is not None
    assert div_nat.canonical_code != div_reg.canonical_code
    # Aucun alias partagé
    assert set(div_nat.aliases).isdisjoint(set(div_reg.aliases))
