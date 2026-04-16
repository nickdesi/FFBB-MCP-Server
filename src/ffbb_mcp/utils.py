import re
from functools import lru_cache
from typing import Any, NamedTuple


def serialize_model(obj: Any) -> Any:
    """Convertit un objet FFBB en dict JSON-serializable."""
    if obj is None:
        return None
    if isinstance(obj, str | int | float | bool):
        return obj

    # Let Pydantic do the heavy lifting natively in C/Rust (V2)
    if hasattr(obj, "model_dump"):  # Pydantic v2
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):  # Pydantic v1
        return obj.dict()

    if isinstance(obj, dict):
        return {k: serialize_model(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize_model(item) for item in obj]

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
    cat_match = re.search(r"U(\d{2})", s)
    categorie: str | None = None
    if cat_match:
        categorie = f"U{cat_match.group(1)}"
    elif "SENIOR" in s or "SENIORS" in s:
        categorie = "SENIOR"

    # 2) Sexe (M/F) — on évite de matcher le M de "U11M" si déjà capturé
    sexe: str | None = None
    if re.search(r"\bM\b", s) or re.search(r"U\d{2}M", s) or "MASC" in s:
        sexe = "M"
    if re.search(r"\bF\b", s) or re.search(r"U\d{2}F", s) or "FÉM" in s or "FEM" in s:
        sexe = "F"

    # 3) Numéro d'équipe (chiffre final non lié à Uxx)
    # On cherche un chiffre en fin de chaîne qui n'est PAS un digit du code Uxx.
    # Exemples : U11M1 → 1, U11M → None, U13F2 → 2, U11 → None
    numero_equipe: int | None = None
    # Retirer le pattern Uxx du début, puis chercher un chiffre isolé restant
    remainder = s
    if cat_match:
        remainder = s[cat_match.end() :]
    # Chercher un chiffre libre (pas partie de Uxx) dans le reste
    num_match = re.search(r"(\d+)", remainder)
    if num_match:
        try:
            numero_equipe = int(num_match.group(1))
        except ValueError:
            numero_equipe = None

    return ParsedCategorie(categorie=categorie, sexe=sexe, numero_equipe=numero_equipe)


def prune_payload(obj: Any, depth: int = 0) -> Any:
    """Réduit agressivement la taille des payloads JSON (ZipAI Surgical Logic).
    - Supprime les valeurs vides (None, [], {}).
    - Limite les dictionnaires à ~10 clés non-essentielles.
    - Limite les listes à 25 éléments maximum.
    """
    # Profondeur max pour éviter toute boucle infinie théorique
    if depth > 10:
        return "<max depth reached>"

    if isinstance(obj, dict):
        # 1. Nettoyage récursif
        cleaned = {
            k: prune_payload(v, depth + 1)
            for k, v in obj.items()
            if v is not None and v != [] and v != {}
        }

        # 2. Élagage chirurgical si trop de clés
        # On préserve toujours les clés "essentielles" pour l'agent
        essential_keys = {
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
        }

        if len(cleaned) > 15:
            sorted_keys = sorted(cleaned.keys())
            kept_keys = {k for k in sorted_keys if k in essential_keys}
            other_keys = [k for k in sorted_keys if k not in essential_keys]

            # On garde les clés essentielles + les 10 premières autres
            for k in other_keys[:10]:
                kept_keys.add(k)

            pruned = {k: cleaned[k] for k in kept_keys}
            if len(other_keys) > 10:
                pruned["_omitted_count"] = len(other_keys) - 10
            return pruned
        return cleaned

    elif isinstance(obj, list):
        # 1. Limitation de taille (ZipAI Surgical)
        limit = 100
        truncated = obj[:limit]

        # 2. Nettoyage récursif
        cleaned_list = [prune_payload(item, depth + 1) for item in truncated]
        final_list = [
            item
            for item in cleaned_list
            if item is not None and item != {} and item != []
        ]

        if len(obj) > limit:
            # On ne peut pas facilement ajouter un champ à une liste sans casser le schéma,
            # mais l'agent verra la troncature.
            pass
        return final_list

    return obj
