# 📚 Référence Complète des Outils FFBB MCP

Ce document fournit une documentation technique exhaustive pour les outils exposés par le serveur FFBB MCP. Il est destiné aux développeurs et aux agents IA pour comprendre les capacités et les schémas de données du serveur.

---

## 🛠️ Outils de Recherche Unifiés

Le serveur a été refondu pour proposer des outils polyvalents qui réduisent le nombre d'appels nécessaires.

### 1. `ffbb_search`

**Description** : Point d'entrée principal pour trouver n'importe quelle entité dans l'écosystème FFBB. Recherche floue via Meilisearch.

- **Arguments** :
  - `query` (string, requis) : Le texte à rechercher (nom de club, ville, nom de compétition, etc.).
  - `type` (enum, défaut: `"all"`) : Filtre le type de résultat.
    - `all` : Cherche partout.
    - `competitions` : Championnats et coupes.
    - `organismes` : Clubs, comités, ligues.
    - `rencontres` : Matchs spécifiques.
    - `salles` : Gymnases et complexes sportifs.
    - `pratiques` : Types de jeu (5x5, 3x3).
    - `terrains` : Terrains extérieurs.
    - `tournois` : Événements ponctuels.
  - `limit` (integer, défaut: `20`) : Nombre maximum de résultats (1-100).

- **Exemple d'appel** :

  ```json
  { "query": "Stade Clermontois", "type": "organismes" }
  ```

- **Retour** : Une liste d'objets contenant au minimum un `id` technique et un `nom`.

---

### 2. `ffbb_get`

**Description** : Récupère les données brutes complètes d'une entité à partir de son identifiant numérique récupéré via `ffbb_search`.

- **Arguments** :
  - `id` (integer|string, requis) : L'ID technique de l'entité.
  - `type` (enum, requis) : Le type d'entité demandée.
    - `competition` : Détails, saisons disponibles et liste des poules.
    - `poule` : **Le plus complet pour un championnat.** Contient le classement ET toutes les rencontres de la saison pour cette poule.
    - `organisme` : Détails admin du club, adresse, et liste des engagements (équipes).

- **Note importante** : `ffbb_get(type='poule')` est la méthode la plus rapide pour obtenir à la fois les scores passés et le calendrier futur d'un groupe.

---

### 3. `ffbb_club`

**Description** : Outil métier dédié aux clubs pour simplifier les workflows courants sans manipuler plusieurs IDs complexes.

- **Arguments** :
  - `action` (enum, requis) : L'opération à effectuer.
    - `calendrier` : Récupère TOUS les matchs (passés et futurs) du club.
    - `equipes` : Liste les équipes engagées par le club (inclut les `poule_id` nécessaires pour d'autres outils).
    - `classement` : Récupère le classement d'une poule spécifique.
  - `organisme_id` (integer, optionnel) : ID du club (préféré pour la précision).
  - `club_name` (string, optionnel) : Nom du club (utilisé si l'ID est inconnu).
  - `filtre` (string, optionnel) : Filtre textuel pour la catégorie (ex: "U13", "Senior F", "NM1").
  - `poule_id` (integer, requis si action=`classement`) : L'identifiant de la poule.

- **Exemple : Récupérer le calendrier des U13 masculins d'un club** :

  ```json
  { "action": "calendrier", "club_name": "JAV", "filtre": "U13M" }
  ```

---

## 🕒 Temps réel et Saisons

### `ffbb_lives`

**Description** : Récupère instantanément tous les matchs en cours (Live Stats). Les scores sont rafraîchis toutes les 30 secondes.

- **Arguments** : Aucun.

### `ffbb_saisons`

**Description** : Liste les saisons sportives disponibles dans la base FFBB.

- **Arguments** :
  - `active_only` (boolean, défaut: `false`) : Si `true`, ne retourne que la saison en cours (ex: 2024-2025).

---

## 🎭 Prompts Prédéfinis (Workflows AI)

Le serveur ne se contente pas de données brutes, il guide l'IA via des prompts système :

1. **`expert_basket`** : Initialise un agent avec les connaissances métiers (règles de désambiguïsation, priorités de recherche).
2. **`bilan_equipe`** : Enchaîne automatiquement la recherche de club, le listing des équipes et la récupération des classements pour produire un rapport.

---

## 💡 Conseils d'utilisation (Best Practices)

1. **Workflow Optimal** :
    - `ffbb_search(query='nom', type='organismes')` -> Récupérer l'ID.
    - `ffbb_club(action='equipes', organisme_id=ID)` -> Trouver l'équipe et son `poule_id`.
    - `ffbb_get(type='poule', id=POULE_ID)` -> Vision complète (Classement + Matchs).

2. **Désambiguïsation** :
    - Si l'utilisateur demande "U13", toujours vérifier s'il s'agit de Masculin (M) ou Féminin (F).
    - Pour les clubs avec plusieurs équipes (ex: U13M-1, U13M-2), l'équipe 1 est toujours celle au niveau le plus haut.

3. **Cache** :
    - Les résultats de recherche et de détails sont mis en cache côté serveur pour optimiser les performances. Ne pas hésiter à répéter des appels similaires.
