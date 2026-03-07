# 📚 Référence des outils FFBB MCP

Ce document détaille chaque outil exposé par le serveur, ses paramètres et son utilité.

---

## 📅 Matchs et Calendrier

### `ffbb_get_lives`

Récupère les matchs de basketball en cours (live). Retourne la liste des rencontres avec les scores actuels, les équipes et le statut du match.

- **Paramètres** : Aucun
- **Usage recommandé** : Suivre les scores en direct le week-end.

### `ffbb_get_saisons`

Récupère la liste de toutes les saisons disponibles.

- **Paramètres** :
  - `active_only` (boolean, optionnel) : Si true, ne retourne que la saison active.
- **Usage recommandé** : Trouver l'année en cours ou l'identifiant pour la saison actuelle.

### `ffbb_calendrier_club`

Recherche les matchs à venir et passés d'un club.

- **Paramètres** :
  - `club_name` (string) : Nom du club (ex: 'ASVEL').
  - `categorie` (string, optionnel) : Catégorie d'âge/sexe (ex: 'U11M').
- **Usage recommandé** : Savoir quand joue une équipe spécifique.

---

## 🏆 Compétitions et Poules

### `ffbb_get_competition`

Détails complets d'une compétition par son ID (nom, type, saisons, poules).

- **Paramètres** : `competition_id` (integer)
- **Note** : Utilisez `ffbb_search_competitions` pour trouver l'ID.

### `ffbb_get_classement`

Récupère uniquement le classement d'une poule (sans les matchs). Très léger.

- **Paramètres** : `poule_id` (integer)
- **Usage recommandé** : Consulter les positions sans charger tout l'historique des matchs.

---

## 🏠 Clubs et Organismes

### `ffbb_get_organisme`

Informations détaillées d'un club (adresse, type, toutes les équipes).

- **Paramètres** : `organisme_id` (integer)

### `ffbb_equipes_club`

Liste allégée des équipes engagées par un club.

- **Paramètres** : `organisme_id` (integer)
- **Usage recommandé** : Éviter de télécharger les adresses et détails admin quand on ne cherche que les équipes.

---

## 🔍 Recherche (Meilisearch)

### `ffbb_multi_search`

Recherche globale sur tous les types FFBB en une seule requête.

- **Paramètres** : `name` (string)
- **Usage recommandé** : Première exploration quand on ne sait pas si le terme désigne un club ou un tournoi.

### `ffbb_search_*`

Série d'outils spécialisés par type :

- `ffbb_search_competitions`
- `ffbb_search_organismes`
- `ffbb_search_rencontres`
- `ffbb_search_salles`
- `ffbb_search_tournois`
- `ffbb_search_terrains`
- `ffbb_search_pratiques`

---

## 📝 Prompts MCP Prédéfinis

Le serveur expose également des **Prompts MCP**. Ceux-ci permettent d'initialiser rapidement un agent ou de formuler une requête complexe avec un contexte prêt à l'emploi.

### `expert_basket`

Configure le LLM pour agir en tant qu'assistant expert en basketball français.

- **Utilité** : Injecte le System Prompt idéal avec les workflows recommandés (point d'entrée, comportement, vérifications).

### `analyser_match`

Génère un prompt pour analyser un match spécifique.

- **Arguments** : `match_id` (string)
- **Utilité** : Demander à l'agent de récupérer le contexte, les enjeux et le résultat probable d'une rencontre.

### `trouver_club`

Aide à trouver un club et ses informations détaillées.

- **Arguments** : `club_name` (string), `department` (string, optionnel)
- **Utilité** : Orchestre la recherche `ffbb_search_organismes` suivie de `ffbb_get_organisme`.

### `prochain_match`

Aide à trouver le prochain match d'une équipe pour un club donné.

- **Arguments** : `club_name` (string), `categorie` (string, optionnel)
- **Utilité** : Appelle `ffbb_calendrier_club` et filtre intelligemment les matchs à venir.

### `classement_poule`

Aide à consulter le classement complet d'une compétition.

- **Arguments** : `competition_name` (string)
- **Utilité** : Construit une suite logique de recherche, récupération des poules, puis affichage du classement.

### `bilan_equipe`

Fait le bilan complet d'une équipe sur toute la saison.

- **Arguments** : `club_name` (string), `categorie` (string)
- **Utilité** : Script un workflow très complet (recherche de club → liste d'équipes → classements pour chaque phase → cumul statistique).
