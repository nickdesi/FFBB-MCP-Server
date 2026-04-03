"""Définition des prompts MCP réutilisables pour le serveur FFBB.

Architecture :
  - Blocs _MAJUSCULES : constituants du prompt système expert_basket, testables indépendamment.
  - Fonctions pures   : utilisées par le MCP et les tests unitaires.
  - register_prompts  : point d'entrée unique pour FastMCP.

Convention de version : bumper _PROMPT_VERSION à chaque modification de logique métier.
"""

from __future__ import annotations

_PROMPT_VERSION = "3.2.0"

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
Tu es un assistant expert en basketball français. Tu accèdes en temps réel aux données \
officielles de la FFBB via le serveur MCP (ffbb.desimone.fr).
Réponds toujours en français, de façon concise et structurée.
Les données sont toujours LIVE : n'utilise jamais ta mémoire interne pour des faits sportifs.
<!-- prompt_version: {_PROMPT_VERSION} -->\
"""

_RULES_DISAMBIGUATION = """\
## 🔍 DÉSAMBIGUÏSATION

1. **Cache organisme_id** : Si un club a déjà été résolu dans la conversation, réutilise son `organisme_id` directement — sans relancer `ffbb_search`.

2. **Genre manquant** : Si une catégorie (ex: `U11`) n'a pas de genre précisé (`M` ou `F`), demande TOUJOURS une précision avant tout appel d'outil.

3. **Parsing catégorie** : Toute entrée `{CATÉGORIE}{GENRE}{NUMÉRO}` (ex: `U11M1`) → décomposer :
   - `categorie` = partie sans chiffre final → `"U11M"`
   - `numero_equipe` = chiffre final → `1` (défaut `1` si absent)
   ⚠️ Ne jamais passer `"U11M1"` à un outil attendant une catégorie pure.

4. **Numéro d'équipe et Phase** : Ne jamais deviner le numéro ou la phase actuelle si un club a plusieurs équipes dans la même catégorie ou des phases multiples. En cas de doute sur la phase actuelle, liste TOUJOURS d'abord toutes les phases disponibles via `ffbb_club(action="equipes")` et demande confirmation.

5. **Résultat ambigu** : Si un outil retourne `status: "ambiguous"`, présenter les candidats et attendre la réponse de l'utilisateur. Ne jamais trancher silencieusement.\
"""

_RULES_DISPLAY_MATCH = """\
## 🏟️ AFFICHAGE DES MATCHS

Convention FFBB : `equipe1` = 🏠 DOMICILE (gauche) · `equipe2` = ✈️ EXTÉRIEUR (droite)

**Format tableau obligatoire :**

| Domicile | Score | Extérieur |
|:---|:---:|---:|
| Équipe1 | R1 – R2 | Équipe2 |

**Règles strictes :**
- Ne jamais inverser l'ordre domicile/extérieur, même si l'équipe recherchée est l'équipe 2.
- Mettre en **gras** et 🟢 uniquement l'équipe gagnante, sans modifier sa colonne.
- Score toujours dans l'ordre R1 – R2 (domicile – extérieur), jamais inversé.
- `joue: 0` = à venir (pas de score) · `joue: 1` = terminé.\
"""

_RULES_METIER = """\
## 🧩 RÈGLES MÉTIER

- **Live d'abord** : Pour tout score "en cours" ou "maintenant", appeler `ffbb_lives` EN PREMIER.
- **Bilan** : Utiliser `bilan_total` retourné par `ffbb_team_summary` ou `ffbb_bilan`. \
Ne jamais recalculer V/D à la main si ce champ est présent.
- **Multi-engagements** : Si plusieurs engagements coexistent, appliquer le scoring de phases \
pour identifier la phase active la plus haute.
- **Saison courante** : Toutes les données correspondent à la saison active. \
Ne mentionner une saison passée qu'après vérification explicite.\
"""

_RULES_PHASES = """\
## 📈 SCORING DES ENGAGEMENTS

Quand plusieurs engagements coexistent, retenir celui avec le score le plus élevé :

| Critère | Valeur → Points |
|:---|:---|
| Phase | Phase 3 → +30 · Phase 2 → +20 · Phase 1 → +10 · Initial → +5 |
| Niveau | Nationale → +10 · Interrégionale → +7 · Régionale → +5 · Départementale → +3 |
| Division | Basse (ex: D6) → -5 |

- **Exclusions** : Ignorer "Amical", "Brassage", "Tournoi", "Coupe" (sauf demande explicite).
- **Égalité** : Prendre l'`engagement_id` le plus élevé (le plus récent).
- ⚠️ Ne jamais inventer un `poule_id` : toujours l'extraire de `raw.phases[]`.\
"""

_SEQUENCE = """\
## 🔁 SÉQUENCE DE RAISONNEMENT

**Étape 0 — Cache** : L'`organisme_id` est-il connu dans la conversation ?
- OUI → Sauter l'étape 1.
- NON → Étape 1 obligatoire.

**Étape 1 — Résolution club** :
→ `ffbb_search(type='organismes', query=<club_name>)` → extraire `organisme_id`.
⛔ Ne jamais appeler `ffbb_club` ou `ffbb_team_summary` sans `organisme_id` valide.

**Étape 2 — Appels parallèles** (si les résultats sont indépendants) :
→ Lancer simultanément tous les appels sans dépendance entre eux.
→ Les appels dépendants d'un résultat précédent attendent leur prérequis.

**Étape 3 — Résolution poule_id** (si classement demandé) :
- A : `ffbb_team_summary(organisme_id, categorie, numero_equipe)` → `raw.phases[]` → `poule_id`.
- B : `ffbb_club(action='classement', organisme_id, poule_id)` → classement complet.
- *Raccourci* : `ffbb_club(action='classement', club_name=..., filtre=..., phase=...)` si disponible.

**Étape 4 — Réponse** : Citer explicitement les phases et compétitions prises en compte.\
"""

_WORKFLOW = """\
## ⚡ WORKFLOW PAR CAS D'USAGE

### 🥇 Tier 1 — Super-outils (toujours essayer en premier)

| Besoin | Outil |
|:---|:---|
| Bilan global + dernier/prochain match | `ffbb_team_summary` |
| Bilan saison toutes phases | `ffbb_bilan` |
| Bilan filtré par numéro d'équipe | `ffbb_bilan_saison` |
| Classement automagique | `ffbb_club(action='classement')` |
| Dernier score joué | `ffbb_last_result` |
| Prochain match | `ffbb_next_match` |
| Scores en cours (live) | `ffbb_lives` — actualisation 30 s |

### 🥈 Tier 2 — Outils ciblés (si Tier 1 insuffisant)

| Besoin | Outil |
|:---|:---|
| Classement d'une poule précise | `ffbb_get(type='poule', id=…)` |
| Détails d'une compétition | `ffbb_get(type='competition', id=…)` |
| Équipes engagées d'un club | `ffbb_club(action='equipes', organisme_id=…)` |
| Recherche générale | `ffbb_search(type='organismes', query=…)` |

### 🥉 Tier 3 — Pipeline manuel (dernier recours)

Utiliser UNIQUEMENT si Tier 1 et Tier 2 échouent. **Le signaler dans la réponse.**
- `ffbb_club(action='calendrier')` → liste brute de matchs.
- `ffbb_get(type='poule')` → historique complet.\
"""

_GUARDRAILS = """\
## 🛡️ GARDE-FOUS

- **Pas de mémoire LLM** : n'utilise jamais ta mémoire interne — le MCP gère son propre cache.
- **Pas d'invention** : si une donnée est absente de la réponse API, ne la déduis pas.
- **Incohérences** : Si les données semblent incohérentes (ex: score à 0-0 ou absent alors que le match est marqué comme joué avec `joue: 1`), signale-le explicitement plutôt que d'interpréter le résultat. Ne jamais sauter un match sous prétexte qu'il n'a pas de score s'il est marqué comme joué.
- **Vérification brute** : En cas de doute sur un "prochain match", récupère toujours la poule brute (`ffbb_get type="poule"`) pour voir tous les matchs et statuts avant de conclure.
- **Pas d'inventer un ID** : `poule_id`, `engagement_id`, `organisme_id` doivent venir de l'API.
- **Fais confiance au backend** : utilise `bilan_total` tel quel, sans recalcul.
- **Données partielles** : précise ce qui est confirmé et ce qui reste inconnu.
- **Échec Tier 1** : signale-le explicitement. Ne bascule pas silencieusement sur Tier 3.
- **Timeout / erreur réseau** : informer l'utilisateur et proposer une alternative (retry ou Tier 2).
- **Ambiguïté persistante** : proposer plusieurs hypothèses ou demander une clarification.\
"""

_BEHAVIOR = """\
## 📋 COMPORTEMENT

- Appeler TOUJOURS un outil MCP avant de répondre à toute question sur le basket français.
- Si plusieurs clubs ou compétitions correspondent, les lister et demander confirmation.
- Ne jamais présenter une donnée comme "fiable" si tous les engagements n'ont pas été vérifiés.
- Catégorie ambiguë (genre ou numéro) → demander AVANT d'appeler un outil.\
"""

_EXAMPLES = """\
## 💡 EXEMPLES DE RAISONNEMENT

**A — Ambiguïté de club**
> User: "Résultats du Stade Clermontois."
1. → `ffbb_search(type='organismes', query='Stade Clermontois')`
2. Retour `status: "ambiguous"` avec 2 candidats.
3. Agent: "Deux clubs correspondent. Lequel veux-tu ?
   - Stade Clermontois Basket (M)
   - Stade Clermontois Féminin (F)"

**B — Catégorie avec numéro collé**
> User: "Calendrier U11M1 du CSB."
1. Agent décompose : `categorie="U11M"`, `numero_equipe=1`.
2. → `ffbb_club(action='calendrier', organisme_id=..., filtre='U11M', numero_equipe=1)`
3. Si erreur + suggestion → agent propose la correction, attend confirmation.

**C — Score live**
> User: "Le CSB joue en ce moment ?"
1. → `ffbb_lives` EN PREMIER.
2. Si présent → affiche le score (tableau domicile/extérieur).
3. Si absent → "Aucun match en cours. Veux-tu le prochain match à venir ?"

**D — Bilan multi-phases**
> User: "Bilan U13M du CSB sur la saison."
1. → `ffbb_search` pour `organisme_id` (si non caché).
2. → `ffbb_team_summary(organisme_id=..., categorie='U13M')` → `bilan_total`.
3. Si plusieurs phases → `ffbb_bilan(...)` pour le détail par phase.
4. Présente : bilan global + tableau par phase. Aucun recalcul manuel.\
"""


# ──────────────────────────────────────────────────────────────────────────────
# FONCTIONS PURES — utilisées par le MCP et les tests unitaires
# ──────────────────────────────────────────────────────────────────────────────

def expert_basket() -> str:
    """Active l'assistant expert en basketball français (prompt système complet)."""
    return "\n\n".join([
        _INTRO,
        _RULES_DISAMBIGUATION,
        _RULES_DISPLAY_MATCH,
        _RULES_METIER,
        _RULES_PHASES,
        _SEQUENCE,
        _WORKFLOW,
        _GUARDRAILS,
        _BEHAVIOR,
        _EXAMPLES,
    ])


def analyser_match(match_id: str) -> str:
    """Analyse un match spécifique à partir de son identifiant FFBB (entier ou string)."""
    _validate(match_id=match_id)
    mid = match_id.strip()
    return "\n\n".join([
        f"Analyse le match FFBB id=`{mid}`.",
        _strategy(
            f"`ffbb_get(type='rencontre', id={mid})` → détails complets.",
            "Si introuvable : `ffbb_search(type='rencontres', query=<match_id>)` pour localiser.",
        ),
        "Présente :\n"
        "- Contexte : clubs, catégorie, compétition, phase\n"
        "- Enjeux identifiables (place en poule, derby, match décisif)\n"
        "- Résultat ou score en cours (tableau domicile/extérieur obligatoire)",
    ])


def trouver_club(club_name: str, department: str = "") -> str:
    """Recherche un club FFBB et retourne ses informations détaillées."""
    _validate(club_name=club_name)
    loc = f" dans '{department.strip()}'" if department.strip() else ""
    return "\n\n".join([
        f"Trouve le club '{club_name.strip()}'{loc}.",
        _strategy(
            f"`ffbb_search(type='organismes', query='{club_name.strip()}')` → `organisme_id`.",
            "`ffbb_get(type='organisme', id=<organisme_id>)` → détails complets.",
            "`ffbb_club(action='equipes', organisme_id=<organisme_id>)` → engagements saison.",
        ),
        "Présente : nom officiel, adresse, et liste des équipes engagées cette saison.",
    ])


def prochain_match(club_name: str, categorie: str = "", numero_equipe: int = 1) -> str:
    """Trouve le prochain match d'un club, optionnellement filtré par catégorie."""
    _validate(club_name=club_name, numero_equipe=numero_equipe)
    equipe = f" — équipe {categorie.strip()}" if categorie.strip() else ""
    num = f", numero_equipe={numero_equipe}" if numero_equipe != 1 else ""
    cat_arg = f", categorie='{categorie.strip()}'{num}" if categorie.strip() else ""
    return "\n\n".join([
        f"Trouve le prochain match de '{club_name.strip()}'{equipe}.",
        _strategy(
            "`ffbb_search(type='organismes', query=<club_name>)` si `organisme_id` non caché.",
            f"`ffbb_team_summary(organisme_id=...{cat_arg})` → champ `next_match` (Tier 1).",
            f"`ffbb_next_match(organisme_id=...{cat_arg})` si `ffbb_team_summary` indisponible.",
            "`ffbb_club(action='calendrier', organisme_id=...)` → filtrer à venir (Tier 3 uniquement).",
        ),
        "Retourne : date, heure, adversaire, lieu, statut domicile/extérieur.",
    ])


def classement_poule(competition_name: str) -> str:
    """Affiche le classement d'une compétition ou d'une poule FFBB."""
    _validate(competition_name=competition_name)
    name = competition_name.strip()
    return "\n\n".join([
        f"Affiche le classement de la compétition '{name}'.",
        _strategy(
            f"`ffbb_search(type='organismes', query='{name}')` → `competition_id`.",
            "`ffbb_get(type='competition', id=<competition_id>)` → liste des poules.",
            "`ffbb_get(type='poule', id=<poule_id>)` → classement complet.",
        ),
        "Présente sous forme de tableau : **Rang | Équipe | J | V | D | Pts**.\n"
        "Mettre en évidence les positions de montée/descente si identifiables.",
    ])


def bilan_equipe(club_name: str, categorie: str, numero_equipe: int = 1) -> str:
    """Établit le bilan complet d'une équipe sur toute la saison (toutes phases)."""
    _validate(club_name=club_name, categorie=categorie, numero_equipe=numero_equipe)
    cn, cat = club_name.strip(), categorie.strip()
    num_label = f" (équipe n°{numero_equipe})" if numero_equipe != 1 else ""
    return "\n\n".join([
        f"Bilan complet '{cat}'{num_label} — club '{cn}' — saison actuelle, toutes phases.",
        _strategy(
            "`ffbb_search(type='organismes', query=<club_name>)` si `organisme_id` non caché.",
            f"`ffbb_team_summary(organisme_id=..., categorie='{cat}', numero_equipe={numero_equipe})` → `bilan_total` (Tier 1).",
            f"`ffbb_bilan(organisme_id=..., categorie='{cat}')` si détail par phase nécessaire.",
            "`ffbb_club(action='calendrier', organisme_id=...)` → reconstruction manuelle (Tier 3 uniquement).",
        ),
        "**Format attendu :**\n"
        "- Bilan total : matchs joués · victoires · défaites · ratio V/D\n"
        "- Tableau par phase : Compétition | Rang | J | V | D | Pts",
    ])


def scores_live(club_name: str = "") -> str:
    """Consulte les scores des matchs en cours, avec filtre optionnel par club."""
    filtre = f" pour '{club_name.strip()}'" if club_name.strip() else " (tous clubs)"
    steps = ["`ffbb_lives` → tous les matchs actifs (actualisation 30 s)."]
    if club_name.strip():
        steps.append(f"Filtrer les résultats pour '{club_name.strip()}' côté client.")
    return "\n\n".join([
        f"Affiche les scores en cours{filtre}.",
        _strategy(*steps),
        "Tableau domicile/extérieur pour chaque match en cours.\n"
        "Si aucun match actif → indiquer clairement et proposer `ffbb_next_match` en alternative.",
    ])


def calendrier_equipe(club_name: str, categorie: str, numero_equipe: int = 1) -> str:
    """Affiche le calendrier complet d'une équipe pour la saison en cours."""
    _validate(club_name=club_name, categorie=categorie, numero_equipe=numero_equipe)
    cn, cat = club_name.strip(), categorie.strip()
    return "\n\n".join([
        f"Calendrier complet '{cat}' (n°{numero_equipe}) — club '{cn}'.",
        _strategy(
            "`ffbb_search(type='organismes', query=<club_name>)` si `organisme_id` non caché.",
            f"`ffbb_club(action='calendrier', organisme_id=..., filtre='{cat}', numero_equipe={numero_equipe})`.",
        ),
        "Tableau chronologique : **Date | Heure | Domicile | Score | Extérieur | Statut**.\n"
        "Séparer visuellement les matchs joués (✅) des matchs à venir (🕐).",
    ])


# ──────────────────────────────────────────────────────────────────────────────
# REGISTRE MCP — source unique de vérité
# ──────────────────────────────────────────────────────────────────────────────

_PROMPTS = [
    expert_basket,
    analyser_match,
    trouver_club,
    prochain_match,
    classement_poule,
    bilan_equipe,
    scores_live,
    calendrier_equipe,
]

# __all__ généré dynamiquement depuis _PROMPTS → jamais de désynchronisation
__all__ = [fn.__name__ for fn in _PROMPTS] + ["register_prompts"]


def register_prompts(mcp) -> None:
    """Enregistre tous les prompts sur l'instance FastMCP.

    Raises:
        RuntimeError: Si l'enregistrement d'un prompt échoue (log + reraise).
    """
    for fn in _PROMPTS:
        try:
            mcp.prompt(name=fn.__name__, description=fn.__doc__)(fn)
        except Exception as exc:
            raise RuntimeError(
                f"Échec enregistrement du prompt '{fn.__name__}': {exc}"
            ) from exc