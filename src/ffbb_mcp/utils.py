import itertools
import os
import re
import sys
import unicodedata
from functools import lru_cache
from typing import Any, NamedTuple

from starlette.responses import JSONResponse

type JSONValue = Any

_DIACRITICS = {
    i: None
    for i in range(sys.maxunicode)
    if unicodedata.category(chr(i)) in ("Mn", "So")
}


def serialize_model(obj: Any) -> JSONValue:
    """Convertit un objet FFBB en dict JSON-serializable."""
    if obj is None:
        return None

    # Fast path: exact primitive types
    obj_type = type(obj)
    if obj_type is str or obj_type is int or obj_type is float or obj_type is bool:
        return obj

    if obj_type is dict:
        return {k: serialize_model(v) for k, v in obj.items()}
    if obj_type is list:
        return [serialize_model(item) for item in obj]

    # Pydantic v2 fast path: model_dump(mode="json") is natively JSON-safe in Rust/C
    if (dump_fn := getattr(obj, "model_dump", None)) is not None:
        return dump_fn(mode="json")

    if (dict_fn := getattr(obj, "dict", None)) is not None:  # Pydantic v1
        return dict_fn()

    # Fallback: isinstance pour supporter les sous-classes (ex: IntEnum)
    if isinstance(obj, (str, int, float, bool)):
        return obj

    if (val := getattr(obj, "__dict__", None)) is not None:
        return {k: serialize_model(v) for k, v in val.items() if not k.startswith("_")}

    return str(obj)


class ParsedCategorie(NamedTuple):
    """Représentation structurée d'une catégorie FFBB.

    Exemple d'entrées supportées : "U11M1", "u13 f 2", "U15", "Senior F".
    """

    categorie: str | None  # ex: "U11", "U13", "SENIOR"
    sexe: str | None  # "M", "F" ou None
    numero_equipe: int | None


_CAT_PATTERN = re.compile(r"\bU-?(\d{1,2})\b|U(\d{1,2})")
_JEUNES_SHORTHAND_PATTERN = re.compile(
    r"\b(?:[RDN]|PN|PR)([MF])(7|9|11|13|15|17|18|20|21)\b"
)
_JEUNES_NAMED_MAP = [
    (re.compile(r"\bBABY(?:[\s_-]?BASKET)?\b"), "U7"),
    (re.compile(r"\bMINI[\s_-]?(?:POUSSIN(?:ES?|S)?|BASKET)\b"), "U9"),
    (re.compile(r"\bPOUSSIN(?:ES?|S)?\b"), "U11"),
    (re.compile(r"\bBENJAMIN(?:ES?|S)?\b"), "U13"),
    (re.compile(r"\bMINIMES?\b"), "U15"),
    (re.compile(r"\bCADET(?:TES?|S)?\b"), "U17"),
    (re.compile(r"\bJUNIORS?\b"), "U20"),
    (re.compile(r"\bESPOIRS?\b"), "U21"),
]
_3X3_PATTERN = re.compile(
    r"\b(3[\s_-]?X[\s_-]?3|SUPERLEAGUE|JUNIORLEAGUE|OPEN[\s_-]?PLUS|OPEN[\s_-]?START)\b"
)
_3X3_CLEANUP_PATTERN = re.compile(r"\b3[\s_-]?X[\s_-]?3\b")
_VETERAN_PATTERN = re.compile(
    r"\b(VETERANS?|VÉTÉRANS?|VET|V35|V40|V45|V50)\b",
)
_SENIOR_PATTERN = re.compile(
    r"\b(SENIORS?|SEN|SE|SEM\d?|SEF\d?|SM\d?|SF\d?|[RDN][MF]\d?|PN[MF]\d?|PR[MF]\d?|[RDN]\d[MF]|PRE[\s-]?NAT(IONALE?)?|PRÉ[\s-]?NAT(IONALE?)?|PRE[\s-]?REG(IONALE?)?|PRÉ[\s-]?RÉG(IONALE?)?|REGION(AL|ALE|ALES|AUX)?|RÉGION(AL|ALE|ALES|AUX)?|DEPARTEMENT(AL|ALE|ALES|AUX)?|DÉPARTEMENT(AL|ALE|ALES|AUX)?|NATION(AL|ALE|ALES|AUX)?|ELITE|ÉLITE)\b",
)
_M_PATTERN = re.compile(
    r"\bM\b|U\d{1,2}M|\b[RDN]M\d?\b|\bPNM\d?\b|\bPRM\d?\b|\bR\dM\b|\bD\dM\b|\bN\dM\b|\bSEM\d?\b|\bSM\d?\b|\bM\d\b|\b(MASC|MASCULIN|MASCULINS|MASCULINE|HOMMES?|GARS|GARCONS?|GARÇONS?|MESSIEURS|CADETS?|BENJAMINS?|POUSSINS?)\b",
)
_F_PATTERN = re.compile(
    r"\bF\b|U\d{1,2}F|\b[RDN]F\d?\b|\bPNF\d?\b|\bPRF\d?\b|\bR\dF\b|\bD\dF\b|\bN\dF\b|\bSEF\d?\b|\bSF\d?\b|\bF\d\b|\b(FÉM|FEM|FEMININ|FÉMININ|FEMININE|FÉMININE|FEMININES|FÉMININES|FILLES?|FEMMES?|DAMES?|CADETTES?|BENJAMINES?|POUSSINES?)\b",
)
_NUM_PATTERN = re.compile(r"(\d+)")


@lru_cache(maxsize=256)
def parse_categorie(raw: str | None) -> ParsedCategorie:
    """Parse une chaîne de catégorie libre en composantes structurées.

    La logique est volontairement tolérante (espaces, casse, tirets) pour
    accepter des entrées utilisateur comme "u11m1", "U11 M 1", "u11-f-2",
    "RM1", "RF2", "DM1", "PNM", "Senior F", "Benjamines 2", "Baby Basket",
    "RM18", "DM15", "3x3", etc.
    """

    if not raw:
        return ParsedCategorie(categorie=None, sexe=None, numero_equipe=None)

    s = raw.strip()
    if not s:
        return ParsedCategorie(categorie=None, sexe=None, numero_equipe=None)

    # ⚡ Bolt: Fast-path par conversion globale en majuscule, supprimant
    # le besoin de re.IGNORECASE sur les expressions régulières.
    s_upper = s.upper()

    # 1) Catégorie type Uxx, jeunes nommés, vétérans, 3x3 ou SENIOR
    cat_match = _CAT_PATTERN.search(s_upper) if "U" in s_upper else None
    shorthand_match = None
    matched_pat = None
    categorie: str | None = None
    sexe: str | None = None

    if cat_match:
        val = cat_match.group(1) or cat_match.group(2)
        categorie = f"U{val}"
    else:
        shorthand_match = _JEUNES_SHORTHAND_PATTERN.search(s_upper)
        if shorthand_match:
            sexe = shorthand_match.group(1)
            categorie = f"U{shorthand_match.group(2)}"
        else:
            for pat, cat_val in _JEUNES_NAMED_MAP:
                named_match = pat.search(s_upper)
                if named_match:
                    categorie = cat_val
                    matched_pat = named_match
                    break
            if not categorie:
                vet_match = _VETERAN_PATTERN.search(s_upper)
                if vet_match:
                    categorie = "VETERAN"
                    matched_pat = vet_match
                elif _SENIOR_PATTERN.search(s_upper):
                    categorie = "SENIOR"
                else:
                    match_3x3 = _3X3_PATTERN.search(s_upper)
                    if match_3x3:
                        categorie = "3X3"
                        matched_pat = match_3x3

    # 2) Sexe (M/F) si non déjà défini par le shorthand jeune
    if sexe is None:
        if _M_PATTERN.search(s_upper):
            if not _F_PATTERN.search(s_upper):
                sexe = "M"
        elif _F_PATTERN.search(s_upper):
            sexe = "F"

    # 3) Numéro d'équipe (chiffre final non lié à Uxx / Vxx / shorthand / 3x3)
    numero_equipe: int | None = None
    remainder = s_upper
    if cat_match:
        remainder = s_upper[cat_match.end() :]
    elif shorthand_match:
        remainder = s_upper[shorthand_match.end() :]
    elif matched_pat:
        remainder = s_upper[matched_pat.end() :]

    if "3" in remainder:
        remainder = _3X3_CLEANUP_PATTERN.sub("", remainder)

    num_match = _NUM_PATTERN.search(remainder)
    if num_match:
        numero_equipe = int(num_match.group(1))

    return ParsedCategorie(categorie=categorie, sexe=sexe, numero_equipe=numero_equipe)


def format_team_name(name: str | None, number: int | str | None) -> str:
    """Formate le nom d'équipe avec son numéro si > 1.

    Exemple : "CS PONT DU CHATEAU", 2 -> "CS PONT DU CHATEAU - 2"
    """
    if not name:
        return ""
    if not number:
        return name

    # ⚡ Bolt: Fast-path for integers avoids try/except and int() overhead
    if type(number) is int:
        if number > 1:
            return f"{name} - {number}"
        return name

    try:
        num_int = int(number)
        if num_int > 1:
            return f"{name} - {num_int}"
    except ValueError, TypeError:
        pass

    return name


_ESSENTIAL_KEYS = frozenset(
    {
        "id",
        "name",
        "type",
        "libelle",
        "status",
        "date",
        "heure",
        "score",
        "equipe",
        "equipe_domicile",
        "equipe_exterieur",
        "domicile",
        "exterieur",
        "equipe1",
        "equipe2",
        "score_equipe1",
        "score_equipe2",
        "score_domicile",
        "score_exterieur",
        "adversaire",
        "club",
        "club_resolu",
        "categorie",
        "position",
        "bilan_total",
        "points",
        "match_joues",
        "gagnes",
        "perdus",
        "nuls",
        "difference",
        "paniers_marques",
        "paniers_encaisses",
        "is_target",
        "logo_url",
        "point_initiaux",
        "penalites_arbitrage",
        "penalites_entraineur",
        "penalites_diverses",
        "nombre_forfaits",
        "nombre_defauts",
        "quotient",
        "hors_classement",
        "salle",
        "ville",
        "adresse",
        "adresse_salle",
        "salle_details",
        "victoire",
        "_meta",
        "candidates",
        "competition_nom",
        "num_journee",
        "journee",
        "phase_courante",
        "phases",
        "played",
        "is_last_match",
        "is_next_match",
        "poule_id",
        "match_id",
        "team",
        "rencontres",
        "classements",
        "classement",
        "engagements",
        "nom",
        "phase",
        "saisons",
        "saison",
        "poule",
        "salles",
    }
)


_PRUNE_LIMIT = int(os.environ.get("FFBB_MCP_PRUNE_LIMIT", "50"))

# Bolt: Pre-calculate the maximum non-essential keys to avoid redundant calculation
# and length determination inside the recursive prune_payload hot path.
_MAX_NON_ESSENTIAL = _PRUNE_LIMIT - len(_ESSENTIAL_KEYS)


def prune_payload(obj: Any, depth: int = 0) -> JSONValue:
    """Réduit agressivement la taille des payloads JSON (ZipAI Surgical Logic).
    - Supprime les valeurs vides (None, [], {}).
    - Limite les dictionnaires à ~10 clés non-essentielles.
    - Limite les listes à 25 éléments maximum.
    """
    # Profondeur max pour éviter toute boucle infinie théorique
    if depth > 10:
        return "<max depth reached>"

    obj_type = type(obj)

    # Fast path: Primitives are the most common payload items.
    if (
        obj_type is str
        or obj_type is int
        or obj_type is float
        or obj_type is bool
        or obj is None
    ):
        return obj

    if obj_type is dict or isinstance(obj, dict):
        # Fusion du nettoyage récursif et de l'élagage en une seule passe
        cleaned: dict[str, Any] = {}
        for k, v in obj.items():
            if v is None:
                continue
            vt = type(v)

            # Fast path for primitives to avoid expensive recursion
            if vt is str or vt is int or vt is float or vt is bool:
                cleaned[k] = v
                continue

            if not v and (vt is list or vt is dict):
                continue

            cleaned_v = prune_payload(v, depth + 1)
            # Post-pruning check
            if cleaned_v is not None:
                cvt = type(cleaned_v)
                if cleaned_v or (cvt is not list and cvt is not dict):
                    cleaned[k] = cleaned_v

        # 2. Élagage chirurgical si trop de clés
        if len(cleaned) > _PRUNE_LIMIT:
            kept: dict[str, Any] = {}
            overflow_count = 0
            non_essential_count = 0
            for k, v in cleaned.items():
                if k in _ESSENTIAL_KEYS:
                    kept[k] = v
                elif non_essential_count < _MAX_NON_ESSENTIAL:
                    kept[k] = v
                    non_essential_count += 1
                else:
                    overflow_count += 1
            if overflow_count:
                kept["_omitted_count"] = overflow_count
            return kept
        return cleaned

    elif obj_type is list or isinstance(obj, list):
        # 1. Limitation de taille (ZipAI Surgical)
        limit = _PRUNE_LIMIT

        # 2. Fusion de la troncature et du nettoyage en une seule passe
        final_list = []

        # ⚡ Bolt: Fast-path for list truncation avoiding enumerate() overhead
        iterable = obj[:limit] if obj_type is list else itertools.islice(obj, limit)

        for item in iterable:
            if item is None:
                continue
            it = type(item)

            # Fast path for primitives to avoid expensive recursion
            if it is str or it is int or it is float or it is bool:
                final_list.append(item)
                continue

            if not item and (it is list or it is dict):
                continue

            cleaned_item = prune_payload(item, depth + 1)
            # Post-pruning check
            if cleaned_item is not None:
                cit = type(cleaned_item)
                if cleaned_item or (cit is not list and cit is not dict):
                    final_list.append(cleaned_item)

        if len(obj) > limit:
            # On ajoute un champ _omitted_count à la fin de la liste pour prévenir l'agent
            final_list.append({"_omitted_count": len(obj) - limit})

        return final_list

    return obj


@lru_cache(maxsize=1024)
def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Calcule la similarité de Jaro-Winkler entre deux chaînes.

    Retourne un float entre 0.0 (complètement différent) et 1.0 (exactement identique).
    """
    if not s1 or not s2:
        return 0.0 if s1 != s2 else 1.0

    # Bolt: Fast path for exact match before string copies/transformations
    # Provides a ~3x speedup by completely bypassing allocation and algorithmic overhead
    if s1 == s2:
        return 1.0

    # Normalisation basique : minuscules et espaces superflus
    s1 = s1.strip().lower()
    s2 = s2.strip().lower()

    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    # Fenêtre de correspondance maximale
    # ⚡ Bolt: Fast-path via explicit bounds checking eliminates max() pure Python overhead
    match_bound = (len1 if len1 > len2 else len2) // 2 - 1
    if match_bound < 0:
        match_bound = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    # Recherche des correspondances dans la fenêtre
    for i in range(len1):
        # ⚡ Bolt: Direct ternary assignment avoids unnecessary variable creation and branch reassignment
        start = i - match_bound if i > match_bound else 0
        end = i + match_bound + 1
        if end > len2:
            end = len2

        s1_i = s1[i]
        for j in range(start, end):
            # ⚡ Bolt: Fast-path string character equality check before list index lookup
            if s1_i == s2[j] and not s2_matches[j]:
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    # Calcul des transpositions
    transpositions = 0
    k = 0
    for i in range(len1):
        if s1_matches[i]:
            while not s2_matches[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1

    t = transpositions // 2

    # Similarité de Jaro
    jaro = (matches / len1 + matches / len2 + (matches - t) / matches) / 3.0

    # Similarité de Jaro-Winkler
    # Recherche de la longueur du préfixe commun (jusqu'à 4 caractères)
    prefix_len = 0
    limit = len1 if len1 < len2 else len2
    if limit > 4:
        limit = 4

    for i in range(limit):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    # Coefficient standard de Winkler : 0.1
    winkler = jaro + prefix_len * 0.1 * (1.0 - jaro)
    return winkler


class OrjsonResponse(JSONResponse):
    """JSONResponse subclass using orjson for high-performance JSON serialization with fallback."""

    def render(self, content: Any) -> bytes:
        try:
            import orjson

            return orjson.dumps(content)
        except ImportError:
            import json

            return json.dumps(content, ensure_ascii=False).encode("utf-8")
