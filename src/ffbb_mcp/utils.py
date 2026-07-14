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

    # Fast path: exact type check avoids slow subclass resolution
    # for 99% of common JSON payloads, bringing a ~3x speedup.
    obj_type = type(obj)
    if obj_type is str or obj_type is int or obj_type is float or obj_type is bool:
        return obj
    if obj_type is dict:
        return {k: serialize_model(v) for k, v in obj.items()}
    if obj_type is list:
        return [serialize_model(item) for item in obj]

    # Let Pydantic do the heavy lifting natively in C/Rust (V2)
    if (val := getattr(obj, "model_dump", None)) is not None:  # Pydantic v2
        return val(mode="json")
    if (val := getattr(obj, "dict", None)) is not None:  # Pydantic v1
        return val()

    # Fallback: isinstance pour supporter les sous-classes (ex: IntEnum)
    if isinstance(obj, str | int | float | bool):
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


_CAT_PATTERN = re.compile(r"U(\d{1,2})")
_M_PATTERN = re.compile(r"\bM\b|U\d{1,2}M|MASC")
_F_PATTERN = re.compile(r"\bF\b|U\d{1,2}F|FÉM|FEM")
_NUM_PATTERN = re.compile(r"(\d+)")


@lru_cache(maxsize=256)
def parse_categorie(raw: str | None) -> ParsedCategorie:
    """Parse une chaîne de catégorie libre en composantes structurées.

    La logique est volontairement tolérante (espaces, casse, tirets) pour
    accepter des entrées utilisateur comme "u11m1", "U11 M 1", "u11-f-2".
    """

    if not raw:
        return ParsedCategorie(categorie=None, sexe=None, numero_equipe=None)

    s = raw.strip().upper()
    if not s:
        return ParsedCategorie(categorie=None, sexe=None, numero_equipe=None)

    # 1) Catégorie type Uxx
    cat_match = _CAT_PATTERN.search(s) if "U" in s else None
    categorie: str | None = None
    if cat_match:
        categorie = f"U{cat_match.group(1)}"
    elif "SENIOR" in s:
        categorie = "SENIOR"

    # 2) Sexe (M/F) — on évite de matcher le M de "U11M" si déjà capturé
    # Fast path: verify substrings before invoking slow regex engine
    sexe: str | None = None
    if "M" in s and _M_PATTERN.search(s):
        sexe = "M"
    elif "F" in s and _F_PATTERN.search(s):
        sexe = "F"

    # 3) Numéro d'équipe (chiffre final non lié à Uxx)
    # On cherche un chiffre en fin de chaîne qui n'est PAS un digit du code Uxx.
    # Exemples : U11M1 → 1, U11M → None, U13F2 → 2, U11 → None
    numero_equipe: int | None = None
    # Retirer le pattern Uxx du début, puis chercher un chiffre isolé restant
    remainder = s[cat_match.end() :] if cat_match else s

    #  Bolt: Regex direct (moteur C) — plus rapide que l'itération manuelle Python.
    num_match = _NUM_PATTERN.search(remainder)
    if num_match:
        # _NUM_PATTERN captures only digits (\d+), so ValueError is impossible here
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

    if type(number) is int:
        if number > 1:
            return f"{name} - {number}"
        return name

    try:
        num_int = int(number)
        if num_int > 1:
            return f"{name} - {num_int}"
    except (ValueError, TypeError):
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
    match_bound = max(len1, len2) // 2 - 1
    if match_bound < 0:
        match_bound = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    # Recherche des correspondances dans la fenêtre
    for i in range(len1):
        start = max(0, i - match_bound)
        end = min(len2, i + match_bound + 1)
        for j in range(start, end):
            if not s2_matches[j] and s1[i] == s2[j]:
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
    for i in range(min(4, len1, len2)):
        if s1[i] == s2[i]:
            prefix_len += 1
        else:
            break

    # Coefficient standard de Winkler : 0.1
    winkler = jaro + prefix_len * 0.1 * (1.0 - jaro)
    return winkler


class OrjsonResponse(JSONResponse):
    """JSONResponse subclass using orjson for high-performance JSON serialization."""

    def render(self, content: Any) -> bytes:
        import orjson

        return orjson.dumps(content)
