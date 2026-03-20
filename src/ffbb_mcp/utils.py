from typing import Any, NamedTuple


def serialize_model(obj: Any) -> Any:
    """Convertit un objet FFBB en dict JSON-serializable."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
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
    sexe: str | None       # "M", "F" ou None
    numero_equipe: int | None


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

    import re

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

    # 3) Numéro d'équipe (dernier chiffre non lié à Uxx)
    numero_equipe: int | None = None
    num_match = re.search(r"(\d)\b(?!.*\d)", s)
    if num_match:
        try:
            numero_equipe = int(num_match.group(1))
        except ValueError:
            numero_equipe = None

    return ParsedCategorie(categorie=categorie, sexe=sexe, numero_equipe=numero_equipe)
