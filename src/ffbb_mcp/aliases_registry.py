"""Registre et résolveur d'alias de compétitions et divisions FFBB.

Charge le fichier YAML versionné et garantit qu'aucune substitution
approximative (ex: NM3 -> PNM, NM2 -> Élite 2) ne soit permise.
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ffbb_mcp.utils import _DIACRITICS

logger = logging.getLogger("ffbb-mcp")


_ALIAS_PUNCT_MAP = str.maketrans("-_.\\'/()", "        ")


def normalize_alias_key(text: str | None) -> str:
    """Normalise un libellé ou code (minuscules, sans accents, sans tirets ni espaces multiples)."""
    if not text:
        return ""

    # ⚡ Bolt: Fast-path for ASCII avoids unicode normalization overhead.
    # When non-ASCII, use precomputed _DIACRITICS translate table to strip accents safely
    if text.isascii():
        clean = text.lower()
    else:
        clean = unicodedata.normalize("NFD", text).translate(_DIACRITICS).lower()

    # ⚡ Bolt: str.translate avoids regex compilation and evaluation overhead (~30-50% speedup)
    return " ".join(clean.translate(_ALIAS_PUNCT_MAP).split())


def compact_alias_key(text: str | None) -> str:
    """Version ultra-compacte sans aucun espace (ex: 'nm 3' -> 'nm3')."""
    return normalize_alias_key(text).replace(" ", "")


class CanonicalDivision(BaseModel):
    """Définition canonique d'une division ou catégorie sportive."""

    key: str
    canonical_code: str
    aliases: list[str] = Field(default_factory=list)
    level: str = "federal"  # federal, regional, departmental, pro
    sex: str | None = None  # M, F
    requires_exact_competition: bool = True
    is_senior: bool = True
    is_espoir: bool = False
    canonical_age: str | None = None  # U13, U15, U18...
    requires_team_number_if_multiple: bool = False


class AliasesRegistry:
    """Registre en mémoire avec index inversé pour une recherche rapide et stricte."""

    def __init__(self, yaml_path: Path | None = None) -> None:
        self.yaml_path = yaml_path or (
            Path(__file__).parent / "data" / "competition_aliases.yaml"
        )
        self.divisions: dict[str, CanonicalDivision] = {}
        self._exact_alias_index: dict[str, CanonicalDivision] = {}
        self._compact_alias_index: dict[str, CanonicalDivision] = {}
        self._load()

    def _load(self) -> None:
        if not self.yaml_path.exists():
            logger.warning(
                "Fichier d'alias %s introuvable, registre vide.", self.yaml_path
            )
            return

        with open(self.yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        aliases_dict = data.get("aliases", {})
        for key, info in aliases_dict.items():
            div = CanonicalDivision(
                key=key,
                canonical_code=info.get("canonical_code", key),
                aliases=info.get("aliases", []),
                level=info.get("level", "federal"),
                sex=info.get("sex"),
                requires_exact_competition=info.get("requires_exact_competition", True),
                is_senior=info.get("is_senior", True),
                is_espoir=info.get("is_espoir", False),
                canonical_age=info.get("canonical_age"),
                requires_team_number_if_multiple=info.get(
                    "requires_team_number_if_multiple", False
                ),
            )
            self.divisions[key] = div

            # Indexer tous les alias
            all_aliases = set(div.aliases)
            all_aliases.add(key)
            all_aliases.add(div.canonical_code)

            for a in all_aliases:
                k_norm = normalize_alias_key(a)
                k_comp = compact_alias_key(a)
                self._exact_alias_index[k_norm] = div
                self._compact_alias_index[k_comp] = div

    def normalize_alias(self, text: str | None) -> str:
        """Normalise un texte d'alias (suppression accents, ponctuation, espaces multiples)."""
        return normalize_alias_key(text)

    def lookup(self, query: str | None) -> CanonicalDivision | None:
        """Résout une division ou catégorie demandée par l'utilisateur."""
        if not query:
            return None

        k_norm = normalize_alias_key(query)
        if k_norm in self._exact_alias_index:
            return self._exact_alias_index[k_norm]

        k_comp = compact_alias_key(query)
        if k_comp in self._compact_alias_index:
            return self._compact_alias_index[k_comp]

        return None

    def is_compatible(
        self,
        requested: str | None,
        comp_code: str | None,
        comp_name: str | None,
    ) -> bool:
        """Vérifie si la compétition amont est strictement compatible avec la division demandée."""
        if not requested:
            return True

        target = self.lookup(requested)
        if target is None:
            # Code ou division non répertoriée dans le registre : vérifier stricte correspondance textuelle
            req_comp = compact_alias_key(requested)
            c_code_comp = compact_alias_key(comp_code)
            c_name_norm = normalize_alias_key(comp_name)
            return req_comp == c_code_comp or req_comp in c_name_norm

        # Si cible trouvée : comparer le code amont
        comp_div = self.lookup(comp_code)
        if comp_div is not None:
            # Compatibilité stricte : ils doivent partager la même clé canonique
            return comp_div.key == target.key

        # Sinon vérifier dans les alias textuels du libellé de la compétition
        c_name_norm = normalize_alias_key(comp_name)
        c_code_norm = normalize_alias_key(comp_code)

        # Pour catégories jeunes : vérifier présence combinée de la tranche d'âge et du genre
        if target.canonical_age and target.sex:
            age_norm = normalize_alias_key(target.canonical_age)
            full_text = f" {c_name_norm} {c_code_norm} "
            if (
                f" {age_norm} " in full_text
                or f"{age_norm}m" in full_text
                or f"{age_norm}f" in full_text
            ):
                if target.sex == "M":
                    has_m = any(
                        w in full_text
                        for w in (
                            " masculin ",
                            " masculine ",
                            " masculins ",
                            " masculines ",
                            " garcon ",
                            " garcons ",
                            f" {age_norm}m ",
                        )
                    )
                    has_f = any(
                        w in full_text
                        for w in (
                            " feminin ",
                            " feminine ",
                            " feminines ",
                            " fille ",
                            " filles ",
                            f" {age_norm}f ",
                        )
                    )
                    if has_m and not has_f:
                        return True
                elif target.sex == "F":
                    has_f = any(
                        w in full_text
                        for w in (
                            " feminin ",
                            " feminine ",
                            " feminines ",
                            " fille ",
                            " filles ",
                            f" {age_norm}f ",
                        )
                    )
                    has_m = any(
                        w in full_text
                        for w in (
                            " masculin ",
                            " masculine ",
                            " masculins ",
                            " garcon ",
                            f" {age_norm}m ",
                        )
                    )
                    if has_f and not has_m:
                        return True

        for a in target.aliases:
            a_norm = normalize_alias_key(a)
            # Match univoque : mot entier ou borne pour éviter que 'nm1' matche dans un mot arbitraire
            if a_norm in (c_code_norm, c_name_norm):
                return True
            if len(a_norm) >= 4 and f" {a_norm} " in f" {c_name_norm} ":
                return True

        return False

    def validate_integrity(self) -> list[str]:
        """Contrôle d'intégrité exécutable en CI pour empêcher les dérives."""
        errors: list[str] = []

        # 1. Vérifier qu'aucun alias n'est partagé entre 2 divisions incompatibles
        seen_aliases: dict[str, str] = {}
        for key, div in self.divisions.items():
            for a in div.aliases:
                c = compact_alias_key(a)
                if c in seen_aliases and seen_aliases[c] != key:
                    errors.append(
                        f"Alias '{a}' (compact: '{c}') déclaré en doublon dans '{key}' et '{seen_aliases[c]}'"
                    )
                seen_aliases[c] = key

        # 2. Vérifier les interdictions canoniques
        # NM3 ne doit pas matcher PNM
        div_nm3 = self.lookup("NM3")
        div_pnm = self.lookup("PNM")
        if div_nm3 and div_pnm and div_nm3.key == div_pnm.key:
            errors.append("INTERDICTION : NM3 et PNM pointent vers la même division !")

        # NM2 ne doit pas matcher ELITE_2
        div_nm2 = self.lookup("NM2")
        div_el2 = self.lookup("ELITE_2")
        if div_nm2 and div_el2 and div_nm2.key == div_el2.key:
            errors.append(
                "INTERDICTION : NM2 et Élite 2 pointent vers la même division !"
            )

        # NM1 ne doit pas matcher NM2
        div_nm1 = self.lookup("NM1")
        if div_nm1 and div_nm2 and div_nm1.key == div_nm2.key:
            errors.append("INTERDICTION : NM1 et NM2 pointent vers la même division !")

        # U15M ne doit pas matcher U15F
        u15m = self.lookup("U15M")
        u15f = self.lookup("U15F")
        if u15m and u15f and u15m.key == u15f.key:
            errors.append(
                "INTERDICTION : U15M et U15F pointent vers la même catégorie !"
            )

        return errors


# Singleton
_REGISTRY: AliasesRegistry | None = None


def get_aliases_registry() -> AliasesRegistry:
    """Retourne l'instance singleton du registre d'alias."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = AliasesRegistry()
    return _REGISTRY
