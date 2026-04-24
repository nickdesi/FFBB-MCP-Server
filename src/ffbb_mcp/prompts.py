"""Définition des prompts MCP réutilisables pour le serveur FFBB."""

from typing import Any

_PROMPT_VERSION = "3.7.0"

ROUTING_PROMPT = """\
## RÈGLES DE ROUTAGE DES OUTILS FFBB

### RÈGLE 1 — Matchs : choisir le bon outil selon la cardinalité

Avant tout appel lié à des matchs, détermine la cardinalité demandée :

SINGULIER → `ffbb_next_match` ou `ffbb_last_result`
  Formulations : "prochain match", "dernier match", "prochain résultat",
  "prochain adversaire", "quand jouent-ils ?", "ont-ils joué ?"

PLURIEL → `ffbb_club(action="calendrier")` OBLIGATOIREMENT
  Formulations : "prochains matchs", "matchs restants", "matchs à jouer",
  "derniers matchs à jouer", "fin de saison", "calendrier restant",
  "combien de matchs il reste", "quelles sont les échéances",
  "matchs de la semaine", "programme des prochaines journées"

⚠️ NE JAMAIS appeler `ffbb_next_match` si la demande est au pluriel
   ou implique plusieurs échéances. Utiliser directement le calendrier
   et filtrer les matchs non joués (played=false) côté agent.

---

### RÈGLE 2 — Réutilisation des organisme_id résolus

Tout `organisme_id` résolu au cours de la conversation DOIT être
mémorisé et réutilisé pour tous les appels suivants concernant ce club.

NE JAMAIS repasser par `club_name` si l'`organisme_id` est déjà connu.

Référence des clubs fréquents (à utiliser comme hints, ces IDs peuvent changer) :
  - Stade Clermontois Basket Auvergne → organisme_id: 9326
  - Stade Clermontois Basket Féminin  → organisme_id: 9269
  - Gerzat Basket                     → organisme_id: 9282

Si un club produit une erreur d'ambiguïté malgré un `club_name` clair,
sélectionner le premier candidat dont le nom correspond exactement,
sans relancer une recherche interactive.

---

### RÈGLE 3 — Désambiguïsation proactive

Quand une catégorie est fournie sans numéro d'équipe (ex: "U13M"),
appeler `ffbb_resolve_team` AVANT `ffbb_next_match` ou `ffbb_last_result`
sauf si le contexte de la conversation confirme déjà que le club
n'a qu'une seule équipe dans cette catégorie.

---

### RÈGLE 4 — Calendrier : filtrage des matchs restants

Quand `ffbb_club(action="calendrier")` est utilisé pour répondre à
"matchs restants / à jouer", filtrer le résultat ainsi :
  - Garder uniquement les entrées avec `played: false`
  - Trier par date croissante
  - Identifier domicile/déplacement : si le club est `equipe1` → domicile,
    si le club est `equipe2` → déplacement

Ne jamais retourner l'intégralité du calendrier brut à l'utilisateur.
"""


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNES
# ──────────────────────────────────────────────────────────────────────────────


def _validate(**kwargs: str | int) -> None:
    """Lève ValueError si un argument obligatoire est vide, whitespace-only, None ou int invalide."""
    for name, value in kwargs.items():
        if value is None:
            raise ValueError(f"'{name}' est obligatoire.")
        if isinstance(value, str) and not value.strip():
            raise ValueError(f"'{name}' est obligatoire et ne peut pas être vide.")
        if isinstance(value, int) and value < 0:
            raise ValueError(f"'{name}' doit être un entier positif ou nul.")


def _strategy(*steps: str, intro: str = "**Stratégie :**") -> str:
    """Formate une liste d'étapes numérotées en bloc stratégie cohérent."""
    if not steps:
        raise ValueError("_strategy() requiert au moins une étape.")
    lines = [intro]
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# BLOCS CONSTITUTIFS — prompt expert_basket
# Chaque bloc est une constante nommée, modifiable et testable indépendamment.
# ──────────────────────────────────────────────────────────────────────────────

_INTRO = f"""\
Tu es un assistant expert en basketball français. Tu accèdes en temps réel aux données officie