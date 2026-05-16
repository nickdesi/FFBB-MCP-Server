import os
import re
from functools import lru_cache
from typing import Any, NamedTuple


def serialize_model(obj: Any) -> Any:
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

    # Fallback: isinstance pour supporter les sous-classes (ex: IntEnum)
    if isinstance(obj, str | int | float | bool):
        return obj

    # Placer la vérification des types de collection natifs (dict/list) avant les
    # vérifications hasattr(). hasattr déclenche des exceptions internes silencieuses
    # coûteuses lorsque l'attribut est manquant, ce qui ralentit la récursion sur de
    # grands payloads JSON standards.
    if isinstance(obj, dict):
        return {k: serialize_model(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize_model(item) for item in obj]

    # Let Pydantic do the heavy lifting natively in C/Rust (V2)
    if hasattr(obj, "model_dump"):  # Pydantic v2
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):  # Pydantic v1
        return obj.dict()

    if hasattr(obj, "__dict__"):
        return {
            k: serialize_model(v)
            for k, v in obj.__dict__.items()
            if not k.startswith("_")
        }
    return str(obj)


class ParsedCategorie(NamedTuple):
    """Représentation structurée d'une catégorie FFBB.

    Exemple d'entrées supportées : "U11M1", "u13 f 2", "U15", "Senior F".
    """

    categorie: str | None  # ex: "U11", "U13", "SENIOR"
    sexe: str | None  # "M", "F" ou None
    numero_equipe: int | None


_CAT_PATTERN = re.compile(r"U(\d{2})")
_M_PATTERN = re.compile(r"\bM\b|U\d{2}M|MASC")
_F_PATTERN = re.compile(r"\bF\b|U\d{2}F|FÉM|FEM")
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
    if "F" in s and _F_PATTERN.search(s):
        sexe = "F"

    # 3) Numéro d'équipe (chiffre final non lié à Uxx)
    # On cherche un chiffre en fin de chaîne qui n'est PAS un digit du code Uxx.
    # Exemples : U11M1 → 1, U11M → None, U13F2 → 2, U11 → None
    numero_equipe: int | None = None
    # Retirer le pattern Uxx du début, puis chercher un chiffre isolé restant
    remainder = s[cat_match.end() :] if cat_match else s

    # Chercher un chiffre libre (pas partie de Uxx) dans le reste
    # ⚡ Bolt: Fast path retiré car l'itération manuelle en Python (for char in remainder)
    # est plus lente que l'invocation directe du moteur Regex en C.
    num_match = _NUM_PATTERN.search(remainder)
    if num_match:
        try:
            numero_equipe = int(num_match.group(1))
        except ValueError:
            numero_equipe = None

    return ParsedCategorie(categorie=categorie, sexe=sexe, numero_equipe=numero_equipe)


def format_team_name(name: str | None, number: int | str | None) -> str:
    """Formate le nom d'équipe avec son numéro si > 1.

    Exemple : "CS PONT DU CHATEAU", 2 -> "CS PONT DU CHATEAU - 2"
    """
    if not name:
        return ""
    if not number:
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
        "club",
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
    }
)


_PRUNE_LIMIT = int(os.environ.get("FFBB_MCP_PRUNE_LIMIT", "50"))


def prune_payload(obj: Any, depth: int = 0) -> Any:
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
        # 1. Nettoyage récursif
        cleaned = {
            k: prune_payload(v, depth + 1)
            for k, v in obj.items()
            # Optimization: avoid empty collection allocation by using type() instead of != []/{} and early exit using boolean truthiness
            if v is not None and (v or (type(v) is not list and type(v) is not dict))
        }

        # 2. Élagage chirurgical si trop de clés
        if len(cleaned) > 50:
            kept: dict[str, Any] = {}
            overflow_count = 0
            non_essential_count = 0
            for k, v in cleaned.items():
                if k in _ESSENTIAL_KEYS:
                    kept[k] = v
                elif non_essential_count < 25:
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
        truncated = obj[:limit]

        # 2. Nettoyage récursif
        cleaned_list = [prune_payload(item, depth + 1) for item in truncated]
        final_list = [
            item
            for item in cleaned_list
            if item is not None
            and (item or (type(item) is not list and type(item) is not dict))
        ]

        if len(obj) > limit:
            # On ajoute un champ _omitted_count à la fin de la liste pour prévenir l'agent
            final_list.append({"_omitted_count": len(obj) - limit})

        return final_list

    return obj
