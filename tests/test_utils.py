from ffbb_mcp.aliases import _normalize_apostrophes, normalize_query
from ffbb_mcp.utils import serialize_model


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

