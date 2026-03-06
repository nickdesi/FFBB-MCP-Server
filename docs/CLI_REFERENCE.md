# 🛠️ Référence des Outils (CLI)

Le serveur **FFBB MCP** expose plus de 15 outils permettant de naviguer dans les données du basket français.

## 🔍 Recherche & Exploration

### `ffbb_multi_search`

La porte d'entrée principale. Recherche simultanément des clubs, compétitions et salles.

- **Paramètre** : `nom` (string) - Le texte à rechercher (ex: "Antibes", "Paris").

### `ffbb_search_organismes`

Recherche uniquement des clubs/organismes.

- **Paramètre** : `nom` (string).

### `ffbb_search_competitions`

Trouve des championnats ou coupes.

- **Paramètre** : `nom` (string).

## 🏀 Matchs & Calendriers

### `ffbb_get_lives`

Récupère tous les scores en direct pour les matchs en cours au moment de l'appel.

### `ffbb_calendrier_club`

Matchs passés et à venir pour un club.

- **Paramètres** :
  - `organisme_id` (int/str) : L'ID officiel du club.
  - `club_name` (optional) : Recherche par nom si l'ID est inconnu.
  - `categorie` (optional) : Filtrer par catégorie (ex: "U15", "Seniors").

### `ffbb_equipes_club`

Liste les équipes engagées par un club dans toutes les divisions.

- **Paramètre** : `organisme_id` (int/str).

## 📊 Classements & Détails

### `ffbb_get_classement`

Affiche le classement actuel d'une poule spécifique.

- **Paramètre** : `poule_id` (int/str).

### `ffbb_get_poule`

Données complètes d'un groupe (matchs, résultats, classement).

- **Paramètre** : `poule_id` (int/str).

### `ffbb_get_competition`

Détails structurels d'une compétition.

- **Paramètre** : `competition_id` (int/str).

## 🏢 Infrastructures

### `ffbb_search_salles`

Trouve des gymnases ou complexes sportifs.

- **Paramètre** : `nom` (string).

### `ffbb_search_terrains`

Recherche des terrains extérieurs (Playgrounds).

- **Paramètre** : `nom` (string).
