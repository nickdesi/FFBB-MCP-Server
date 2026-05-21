from ffbb_mcp.aliases import _normalize_apostrophes, normalize_query
from ffbb_mcp.utils import (
    jaro_winkler_similarity,
    parse_categorie,
    prune_payload,
    serialize_model,
)


def test_serialize_simple_types():
    assert serialize_model(1) == 1
    assert serialize_model("test") == "test"
    assert serialize_model(True) is True
    assert serialize_model(None) is None


def test_serialize_dict():
    data = {"a": 1, "b": "test"}
    assert serialize_model(data) == data


def test_serialize_list():
    data = [1, "test", {"a": 1}]
    assert serialize_model(data) == data


class DemoObject:
    def __init__(self):
        self.a = 1
        self._private = 2

    def method(self):
        pass


def test_serialize_object():
    obj = DemoObject()
    serialized = serialize_model(obj)
    assert serialized == {"a": 1}
    assert "_private" not in serialized


# ---------------------------------------------------------------------------
# Tests — Bug 1 : normalisation des apostrophes
# ---------------------------------------------------------------------------


class TestNormalizeApostrophes:
    """Vérifie que _normalize_apostrophes remplace toutes les variantes."""

    def test_right_single_quotation_mark(self):
        # U+2019 — apostrophe typographique française
        assert _normalize_apostrophes("Jeanne\u2019Arc") == "Jeanne\u0027Arc"

    def test_left_single_quotation_mark(self):
        # U+2018
        assert _normalize_apostrophes("d\u2018Arc") == "d\u0027Arc"

    def test_single_high_reversed_9(self):
        # U+201B
        assert _normalize_apostrophes("l\u201bOrchestre") == "l\u0027Orchestre"

    def test_backtick(self):
        assert _normalize_apostrophes("l\u0060Arc") == "l\u0027Arc"

    def test_ascii_apostrophe_unchanged(self):
        assert _normalize_apostrophes("Jeanne d\u0027Arc") == "Jeanne d\u0027Arc"

    def test_no_apostrophe_unchanged(self):
        assert _normalize_apostrophes("Vichy") == "Vichy"

    def test_multiple_apostrophes(self):
        assert _normalize_apostrophes("\u2019i\u2018j") == "\u0027i\u0027j"


class TestNormalizeQueryApostrophe:
    """Vérifie que normalize_query normalise les apostrophes avant la recherche."""

    def test_typographic_apostrophe_in_club_name(self):
        # "Jeanne d\u2019Arc Vichy" doit produire le même résultat que "Jeanne d'Arc Vichy"
        result_typo = normalize_query("Jeanne d\u2019Arc Vichy")
        result_ascii = normalize_query("Jeanne d'Arc Vichy")
        assert result_typo == result_ascii

    def test_alias_lookup_with_typographic_apostrophe(self):
        # "jav" est un alias de "jeanne d'arc vichy"
        # La résolution doit fonctionner même si la requête utilise une apostrophe typographique
        result = normalize_query("ja vichy")
        assert "jeanne" in result.lower() or "vichy" in result.lower()

    def test_empty_string_unchanged(self):
        assert normalize_query("") == ""


class TestPrunePayload:
    """Vérifie le fonctionnement de l'élagage chirurgical ZipAI."""

    def test_prune_simple_dict(self):
        data = {
            "id": 1,
            "name": "Vichy",
            "description": "Un club de basket",
            "extra": "data",
        }
        pruned = prune_payload(data)
        # Champs standards préservés
        assert pruned["id"] == 1
        assert pruned["name"] == "Vichy"
        # Champs non-standards préservés si petit nombre
        assert pruned["description"] == "Un club de basket"
        assert pruned["extra"] == "data"

    def test_prune_large_dict(self):
        # Créer un dictionnaire avec beaucoup de champs
        data = {f"field_{i}": i for i in range(20)}
        data["id"] = "fixed"
        data["name"] = "fixed_name"

        pruned = prune_payload(data)
        assert pruned["id"] == "fixed"
        assert pruned["name"] == "fixed_name"
        # Le nombre total de champs doit être limité (~10 + standards)
        assert len(pruned) <= 60

    def test_prune_list_limit(self):
        data = [{"index": i, "id": i} for i in range(150)]
        pruned = prune_payload(data)
        assert isinstance(pruned, list)
        assert len(pruned) <= 100  # Limite par défaut
        assert pruned[0]["id"] == 0

    def test_prune_recursive(self):
        data = {"id": 1, "sub": {"id": 2, "deep": {f"f{i}": i for i in range(20)}}}
        pruned = prune_payload(data)
        assert pruned["sub"]["id"] == 2
        assert len(pruned["sub"]["deep"]) <= 25

    def test_prune_non_dict(self):
        assert prune_payload(123) == 123
        assert prune_payload("hello") == "hello"
        assert prune_payload(None) is None


class TestParseCategorie:
    """Vérifie le parsing robuste des catégories FFBB, y compris U7 et U9."""

    def test_parse_standard_u_double_digit(self):
        res = parse_categorie("U11M1")
        assert res.categorie == "U11"
        assert res.sexe == "M"
        assert res.numero_equipe == 1

        res2 = parse_categorie("u13 f 2")
        assert res2.categorie == "U13"
        assert res2.sexe == "F"
        assert res2.numero_equipe == 2

    def test_parse_u_single_digit(self):
        # Bug corrigé : support de U9 et U7
        res = parse_categorie("U9")
        assert res.categorie == "U9"
        assert res.sexe is None
        assert res.numero_equipe is None

        res2 = parse_categorie("u9m1")
        assert res2.categorie == "U9"
        assert res2.sexe == "M"
        assert res2.numero_equipe == 1

        res3 = parse_categorie("U7F")
        assert res3.categorie == "U7"
        assert res3.sexe == "F"
        assert res3.numero_equipe is None

        res4 = parse_categorie("u7 f 2")
        assert res4.categorie == "U7"
        assert res4.sexe == "F"
        assert res4.numero_equipe == 2

    def test_parse_seniors(self):
        res = parse_categorie("Senior F")
        assert res.categorie == "SENIOR"
        assert res.sexe == "F"
        assert res.numero_equipe is None

        res2 = parse_categorie("SENIORS MASCULINS 2")
        assert res2.categorie == "SENIOR"
        assert res2.sexe == "M"
        assert res2.numero_equipe == 2

    def test_parse_edge_cases(self):
        assert parse_categorie("") == (None, None, None)
        assert parse_categorie(None) == (None, None, None)
        assert parse_categorie("   ") == (None, None, None)


class TestJaroWinklerSimilarity:
    """Vérifie le calcul de la similarité de Jaro-Winkler."""

    def test_exact_match(self):
        assert jaro_winkler_similarity("Vichy", "Vichy") == 1.0
        assert jaro_winkler_similarity("  Vichy  ", "vichy") == 1.0

    def test_completely_different(self):
        assert jaro_winkler_similarity("ABC", "XYZ") == 0.0

    def test_empty_cases(self):
        assert jaro_winkler_similarity("", "") == 1.0
        assert jaro_winkler_similarity(None, None) == 1.0
        assert jaro_winkler_similarity("Vichy", "") == 0.0
        assert jaro_winkler_similarity("", "Vichy") == 0.0

    def test_standard_cases(self):
        # Martha vs Marhta
        sim1 = jaro_winkler_similarity("martha", "marhta")
        assert 0.9 < sim1 < 1.0

        # Dixon vs Dicksonx
        sim2 = jaro_winkler_similarity("dixon", "dicksonx")
        assert 0.7 < sim2 < 0.9

    def test_club_names_prefix(self):
        # Les préfixes identiques doivent donner un score élevé (grâce au Winkler boost)
        sim_club = jaro_winkler_similarity(
            "CS PONT DU CHATEAU", "CS PONT DU CHATEAU - 2"
        )
        assert sim_club > 0.85
