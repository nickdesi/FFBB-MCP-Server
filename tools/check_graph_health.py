"""Vérifie la santé du graphe FFBB MCP via le rapport Graphify.

Extrait les métriques critiques du fichier GRAPH_REPORT.md et compare
aux seuils définis. Retourne exit 0 si OK, 1 si échec.

Note d'usage (depuis 1.5.1) :
- Ce script n'est plus exécuté par la CI (rapport Graphify non versionné).
- Il reste appelé en pré-déploiement par tools/deploy.sh (non-bloquant)
  et exposé via tools/helpers.sh:run_graph_health() pour diagnostic manuel.
- Pour le rafraîchir avant ce check : `rtk graphify update .` (no LLM cost).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "graphify-out" / "GRAPH_REPORT.md"

# Couleurs ANSI pour le terminal
VERT = "\033[92m"
ROUGE = "\033[91m"
JAUNE = "\033[93m"
RESET = "\033[0m"
GRAS = "\033[1m"

# Seuils de santé du graphe
# Note : import_cycles=3 accepte les lazy imports intentionnels dans
# common.py, cache_strategy.py et client.py (vérifié par audit)
SEUILS = {
    "import_cycles": {"max": 3, "label": "Import cycles"},
    "extraction_rate": {"min": 90, "label": "Extraction rate"},
    "isolated_nodes": {"max": 400, "label": "Isolated nodes"},
    "inferred_edges": {"max": 200, "label": "INFERRED edges"},
    "thin_communities": {"max": 40, "label": "Thin communities"},
}


def _lire_rapport() -> str:
    """Lit le fichier GRAPH_REPORT.md ou lève une erreur explicite."""
    if not REPORT_PATH.exists():
        print(
            f"{ROUGE}ERREUR : Fichier non trouvé{RESET}\n"
            f"  Chemin attendu : {REPORT_PATH}\n"
            f"  Générez-le avec : graphify analyze src/ffbb_mcp"
        )
        sys.exit(1)
    return REPORT_PATH.read_text(encoding="utf-8")


def _extraire_valeur(pattern: str, texte: str, cast: type = int) -> float | int | None:
    """Extrait une valeur numérique depuis le rapport via regex."""
    match = re.search(pattern, texte, re.IGNORECASE)
    if not match:
        return None
    valeur = match.group(1).replace(",", "").replace("%", "")
    try:
        return cast(valeur)
    except ValueError, TypeError:
        return None


def _compter_cycles_import(texte: str) -> int | None:
    """Compte le nombre total de cycles d'import dans le rapport.

    Format attendu dans GRAPH_REPORT.md :
        ## Import Cycles
        - 1-file cycle: `...`
        - 3-file cycle: `...`
    """
    cycles = re.findall(r"^\s*-\s+\d+-file cycle:", texte, re.MULTILINE)
    return len(cycles) if cycles else 0


def _extraire_metriques(texte: str) -> dict[str, float | int | None]:
    """Extrait toutes les métriques depuis le contenu du rapport."""
    # Extraction rate : "Extraction: 92% EXTRACTED"
    extraction = _extraire_valeur(
        r"Extraction:\s*(\d+(?:\.\d+)?)\s*%\s*EXTRACTED", texte, float
    )
    # Isolated nodes : "145 isolated node(s)"
    isolated = _extraire_valeur(r"(\d+)\s+isolated\s+node", texte)
    # INFERRED edges : "INFERRED: 138 edges"
    inferred = _extraire_valeur(r"INFERRED:\s*(\d+)\s+edge", texte)
    # Thin communities : "37 thin omitted" ou "37 thin communities"
    thin = _extraire_valeur(r"(\d+)\s+thin\s+(?:communit|omitted)", texte)

    return {
        "import_cycles": _compter_cycles_import(texte),
        "extraction_rate": extraction,
        "isolated_nodes": isolated,
        "inferred_edges": inferred,
        "thin_communities": thin,
    }


def _verifier_seuil(cle: str, valeur: float | int | None) -> tuple[str, bool, str]:
    """Vérifie si une valeur respecte le seuil. Retourne (label, ok, détail)."""
    seuil = SEUILS[cle]
    label = seuil["label"]

    if valeur is None:
        return (label, False, "Métrique non trouvée dans le rapport")

    if "max" in seuil:
        ok = valeur <= seuil["max"]
        detail = f"{valeur} (seuil: ≤{seuil['max']})"
    else:
        ok = valeur >= seuil["min"]
        detail = f"{valeur}% (seuil: ≥{seuil['min']}%)"

    return (label, ok, detail)


def main() -> int:
    """Point d'entrée principal. Retourne 0 si OK, 1 si échec."""
    print(f"\n{GRAS}🔍 Vérification de la santé du graphe FFBB MCP{RESET}\n")

    texte = _lire_rapport()
    metriques = _extraire_metriques(texte)

    resultats: list[tuple[str, bool, str]] = []
    for cle in SEUILS:
        resultats.append(_verifier_seuil(cle, metriques[cle]))

    nb_ok = 0
    nb_total = len(resultats)
    nb_alertes = 0

    for label, ok, detail in resultats:
        if ok:
            icone = f"{VERT}✅{RESET}"
            nb_ok += 1
        else:
            # Alerte jaune si la valeur est proche du seuil (≥80%), rouge sinon
            icone = f"{ROUGE}❌{RESET}"
            nb_alertes += 1
        print(f"  {icone} {label:<20s}: {detail}")

    print()
    if nb_ok == nb_total:
        print(f"  {VERT}{GRAS}📊 Résultat : {nb_ok}/{nb_total} métriques OK{RESET}")
        return 0
    else:
        print(
            f"  {ROUGE}{GRAS}📊 Résultat : {nb_ok}/{nb_total} métriques OK "
            f"({nb_alertes} échec(s)){RESET}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
