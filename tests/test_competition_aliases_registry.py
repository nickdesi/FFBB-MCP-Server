"""Tests de validation et de non-régression du registre des alias de compétition.

Garantit le respect absolu des règles d'intégrité canoniques :
- Aucun alias partagé entre divisions incompatibles
- NM3 != PNM, NM2 != Élite 2, NM1 != NM2
- U15M != U15F, etc.
"""

from ffbb_mcp.aliases_registry import get_aliases_registry


def test_registry_integrity_validation():
    """Vérifie qu'aucune anomalie de schéma ou collision d'alias n'est présente."""
    registry = get_aliases_registry()
    errors = registry.validate_integrity()
    assert errors == [], f"Erreurs d'intégrité détectées dans le registre : {errors}"


def test_nm3_does_not_match_pnm():
    registry = get_aliases_registry()
    nm3 = registry.lookup("NM3")
    pnm = registry.lookup("PNM")
    assert nm3 is not None
    assert pnm is not None
    assert nm3.key != pnm.key
    assert registry.is_compatible("NM3", "PNM", "PRE NATIONALE MASCULINE") is False
    assert registry.is_compatible("PNM", "NM3", "NATIONALE MASCULINE 3") is False


def test_nm2_does_not_match_elite2():
    registry = get_aliases_registry()
    nm2 = registry.lookup("NM2")
    el2 = registry.lookup("ELITE_2")
    assert nm2 is not None
    assert el2 is not None
    assert nm2.key != el2.key
    assert registry.is_compatible("NM2", "ELIT2", "ELITE 2") is False
    assert registry.is_compatible("ELITE_2", "NM2", "NATIONALE MASCULINE 2") is False


def test_nm1_does_not_match_nm2():
    registry = get_aliases_registry()
    nm1 = registry.lookup("NM1")
    nm2 = registry.lookup("NM2")
    assert nm1 is not None
    assert nm2 is not None
    assert nm1.key != nm2.key
    assert registry.is_compatible("NM1", "NM2", "NATIONALE MASCULINE 2") is False


def test_u15m_does_not_match_u15f():
    registry = get_aliases_registry()
    u15m = registry.lookup("U15M")
    u15f = registry.lookup("U15F")
    assert u15m is not None
    assert u15f is not None
    assert u15m.key != u15f.key
    assert u15m.sex == "M"
    assert u15f.sex == "F"


def test_unicode_normalization_preserves_division_semantics():
    registry = get_aliases_registry()
    # Casse et accents
    assert registry.lookup("élite 2") == registry.lookup("ELITE 2")
    assert registry.lookup("pré nationale masculine") == registry.lookup("PNM")
    assert registry.lookup("Nationale Masculine 3") == registry.lookup("NM3")


def test_elite2_aliases_map_to_same_canonical_value():
    registry = get_aliases_registry()
    aliases = ["Élite 2", "Elite 2", "ELIT2", "ELITE 2"]
    keys = {registry.lookup(a).key for a in aliases if registry.lookup(a)}
    assert len(keys) == 1
    assert "ELITE_2" in keys


def test_unknown_division_returns_not_found():
    registry = get_aliases_registry()
    assert registry.lookup("INVENTED_DIV_XYZ") is None
