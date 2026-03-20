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

- **Sortie pour `action="equipes"`** : tableau d'objets avec, pour chaque équipe engagée :
  - `team_id` : identifiant stable de l'engagement (alias d'`engagement_id`).
  - `engagement_id` : identifiant FFBB brut de l'engagement.
  - `numero_equipe` : numéro d'équipe dans la catégorie ("1", "2", ...), si disponible.
  - `team_label` : label prêt à l'emploi pour les agents, ex: `"Stade Clermontois U11M1"`.
  - `phase_label` : libellé de phase si disponible (ex: `"Phase 1"`).
  - `nom_equipe` : nom du club.
  - `competition` / `competition_id` : libellé et ID de la compétition.
  - `poule_id` : poule associée à cette équipe (utilisable avec `ffbb_get(type='poule')`).
  - `sexe` : "M", "F" ou vide.
  - `categorie` : code de catégorie (ex: "U11").
  - `niveau` : niveau de la compétition (si fourni par l'API FFBB).

- **Exemple : Récupérer le calendrier des U13 masculins d'un club** :

  ```json
  { "action": "calendrier", "club_name": "JAV", "filtre": "U13M" }
  ```

### action="calendrier" — calendrier d’un club

Le calendrier club s’appuie sur `get_calendrier_club_service` et renvoie une liste de matchs simplifiés pour un club et une catégorie donnés.

**Contrat de données garanti** :

- Les matchs sont **triés par date croissante** (du plus ancien au plus récent).
- La zone horaire utilisée pour l’interprétation des dates est **Europe/Paris**.
- Pour chaque match, les champs suivants existent au minimum :
  - `id`: identifiant FFBB de la rencontre.
  - `date`: date (et éventuellement heure) brute telle que renvoyée par l’API FFBB.
  - `equipe1`, `equipe2`: noms des deux équipes.
  - `score_equipe1`, `score_equipe2`: scores si disponibles (sinon `null`/vide).
  - `competition_nom`: libellé de la compétition.
  - `num_journee`: numéro de journée si disponible.
  - `played` (`bool`):
    - `true` si le match est considéré comme joué (score présent ou date passée),
    - `false` si le match est à venir.
  - `is_last_match` (`bool`):
    - `true` pour **au plus un** match : le **dernier match joué** dans la liste retournée ;
    - `false` pour tous les autres.
  - `is_next_match` (`bool`):
    - `true` pour **au plus un** match : le **prochain match à venir** dans la liste retournée ;
    - `false` pour tous les autres.

> Remarque : `played`, `is_last_match` et `is_next_match` sont calculés **sur la liste effectivement renvoyée** après tri et éventuelle troncature.

**Troncature et performances** :

- Pour protéger les performances, un plafond global `FFBB_MAX_CALENDAR_MATCHES` (par défaut `300`) est appliqué.
- Si le nombre de matchs dépasse cette limite, la liste est tronquée après tri et flags.
- Dans ce cas, un dernier élément supplémentaire est ajouté à la fin du résultat :

  ```jsonc
  {
    "warning": "Résultat tronqué côté MCP: trop de matchs pour ce club/catégorie. Affichage limité pour protéger les performances. Affinez votre requête (catégorie précise, équipe 1/2, phase, etc.).",
    "total_initial": <nombre_total_de_matchs_avant_troncature>,
    "limite_appliquee": <valeur_effective_de_FFBB_MAX_CALENDAR_MATCHES>
  }
  ```

Cela permet aux agents de :

- Obtenir le **dernier résultat** (`is_last_match == true`).
- Obtenir le **prochain match** (`is_next_match == true`).
- Parcourir le calendrier dans l’ordre chronologique sans avoir à refaire un tri ou une classification temporelle côté LLM.

---

### 4. `ffbb_resolve_team`

**Description** : Résout une **équipe unique** d'un club pour une catégorie donnée, en encapsulant
la logique de désambiguïsation (U11M1, U13F-2, etc.).

- **Arguments** :
  - `club_name` (string, optionnel) : Nom du club (ex: `"Stade Clermontois"`).
  - `organisme_id` (integer|string, optionnel) : ID FFBB du club (plus fiable que `club_name`).
  - `categorie` (string, requis) : Catégorie + genre + numéro d'équipe (ex: `"U11M1"`, `"U13F2"`, `"U15M"`).

  > Au moins l'un de `club_name` ou `organisme_id` doit être fourni.

- **Retour** : un objet JSON structuré :

  - `team` : l'équipe résolue (ou `null` en cas d'ambiguïté), avec la même structure que
    les entrées de `ffbb_club(action="equipes")` :
    - `team_id`, `engagement_id`, `numero_equipe`, `team_label`, `phase_label`,
      `nom_equipe`, `competition`, `competition_id`, `poule_id`, `sexe`, `categorie`, `niveau`.
  - `candidates` : tableau de toutes les équipes candidates correspondant à la catégorie,
    même structure que ci-dessus.
  - `ambiguity` : message textuel expliquant l'ambiguïté si plusieurs équipes
    correspondent et qu'aucune sélection automatique n'est possible.

**Règles de désambiguïsation** :

1. Si une seule équipe correspond à la catégorie filtrée, `team` contient cette équipe et
   `ambiguity` vaut `null`.
2. Si la catégorie ne précise **pas** le numéro d'équipe (ex: `"U11M"`) et que plusieurs
   équipes existent, le service tente de privilégier l'équipe n°1 (`numero_equipe == "1"`)
   ou les engagements sans `numero_equipe`.
3. Si malgré tout plusieurs équipes restent candidates, `team` vaut `null` et
   `ambiguity` explique qu'il faut demander à l'utilisateur de préciser le numéro
   d'équipe (1, 2, ...) ou la phase.

**Exemple d'appel** :

```json
{ "club_name": "Stade Clermontois", "categorie": "U11M1" }
```

**Exemple d'usage agent** :

1. Appeler `ffbb_resolve_team` pour identifier précisément `U11M1` d'un club.
2. Lire `team.poule_id` et utiliser `ffbb_get(type="poule", id=team.poule_id)` pour
   obtenir le calendrier complet + classement.

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

1. **Outil prioritaire pour bilans/classements**
   - Pour tout ce qui concerne le **bilan complet d’une équipe**, ses **résultats** ou son **classement** sur la saison, utilise en priorité :
     - `ffbb_bilan(club_name=..., categorie=...)` → **un seul appel** agrège toutes les phases en interne.
   - Ne reconstruis pas le bilan "à la main" à partir de `ffbb_get` ou `ffbb_club` si `ffbb_bilan` est disponible.

2. **Workflow club → équipe → poule**
   - Pour naviguer d’un club vers la bonne poule :
     - `ffbb_search(type='organismes', query='nom')` → récupérer l’`organisme_id`.
     - `ffbb_club(action='equipes', organisme_id=ID)` → lister les équipes, catégories et `poule_id`.
     - `ffbb_get(type='poule', id=POULE_ID)` → vision complète de la poule (**classement + tous les matchs**).

3. **Anti‑pattern à éviter (calendrier)**
   - Si tu connais déjà un `poule_id`,
     - **utilise toujours** `ffbb_get(type='poule', id=POULE_ID)` pour récupérer classement + rencontres.
     - N’utilise `ffbb_club(action='calendrier')` **qu’en dernier recours**, lorsque tu n’as réellement aucun `poule_id` exploitable.

4. **Données live et cache**
   - Les données FFBB sont **toujours live** côté API officielle.
   - Ne suppose jamais l’existence d’un cache côté LLM ou côté utilisateur :
     - pour connaître un résultat, un classement ou un calendrier à jour, tu dois **appeler les outils**.
   - Le serveur MCP gère déjà un cache interne optimisé ; le LLM n’a pas à se préoccuper de la couche cache.

5. **Désambiguïsation des catégories**
   - Si l’utilisateur donne une catégorie ambiguë (ex. `"U13"` sans préciser Masculin/Féminin ni le numéro d’équipe), demande toujours des précisions :
     - Genre : `M` ou `F` (ex. `U13M`, `U13F`).
     - Numéro d’équipe lorsqu’il y en a plusieurs (`U13M-1`, `U13M-2`, etc.).
   - Ne sélectionne pas arbitrairement une équipe en cas d’ambiguïté : priorise la demande d’informations supplémentaires.

6. **Répétition d’appels**
   - Répéter un même appel d’outil avec les mêmes paramètres est acceptable :
     - les résultats de recherche, bilans et détails sont mis en cache côté serveur MCP pour optimiser les performances.
   - Inutile d’essayer d’optimiser les appels côté LLM en réutilisant "de mémoire" des résultats potentiellement obsolètes.

---

## 🧪 Benchmarks & seuils P95 (CI)

Pour vérifier que les services restent performants dans le temps, le dépôt fournit
un petit utilitaire de benchmark : `tools/measure_services.py`.

- Il exécute en boucle (mocks FFBB, caches vidés) :
  - `ffbb_bilan_service(organisme_id=9326, categorie="U11M1")`
  - `get_calendrier_club_service(organisme_id=9326, categorie="U11M1")`
- Il calcule pour chaque service :
  - `mean`, `median`, `p95`, `min`, `max`.
- Il peut **casser le build** en CI si les P95 dépassent un seuil.

### Lancer le benchmark en local

```bash
uv run python tools/measure_services.py
```

Variables d'environnement utiles :

- `SIMULATE_LATENCY_MS` : ajoute une latence artificielle (ms) sur `get_poule_async`
  pour simuler des réseaux plus lents.
- `THRESHOLD_P95_BILAN` : si > 0, le script retourne un code de sortie non nul
  si le P95 de `ffbb_bilan_service` dépasse ce seuil (en secondes).
- `THRESHOLD_P95_CAL` : même principe pour `get_calendrier_club_service`.

Exemple d'usage en CI (pseudo-code) :

```bash
THRESHOLD_P95_BILAN=0.300 \
THRESHOLD_P95_CAL=0.350 \
uv run python tools/measure_services.py
```

Si l'un des P95 dépasse le seuil, le script affiche un message d'erreur explicite
et sort avec `exit 1`, ce qui permet de faire échouer le job CI.


## 🔐 Sécurité, validation & garde-fous

Plusieurs garde-fous sont mis en place au niveau des tools et services pour
protéger l'API FFBB et éviter des réponses inutilisables pour les LLM :

- **Validation des paramètres** au niveau des tools MCP :
  - limites sur `limit` pour `ffbb_search` (via `FFBB_MAX_RESULTS_LIMIT`),
  - erreurs explicites quand des combinaisons de paramètres sont incohérentes
    (par ex. catégorie manquante ou ambiguë).
- **Garde-fous de taille** (voir aussi la section « Limites & garde-fous de taille ») :
  - troncature des gros calendriers via `FFBB_MAX_CALENDAR_MATCHES` avec ajout
    d'un objet `{"warning": "Résultat tronqué ..."}` en fin de liste,
  - limites sur le nombre de résultats `search` pour éviter les payloads énormes.
- **Erreurs explicites de haut niveau** (McpError) :
  - messages orientés assistant (FR) pour guider la reformulation
    (ajouter le genre, préciser le numéro d'équipe, etc.),
  - codes d'erreur stables (`INTERNAL_ERROR`, `BAD_REQUEST`, ...).
- **Logs de performance structurés** via `_log_timing` :
  - chaque service critique logue `event`, `duration_s` et quelques champs clés
    (ex. `categorie`, `matches_count`, `truncated`),
  - permet de suivre les dérives de latence sans exposer de détails sensibles.

Pour ajouter un nouveau tool ou service, il est recommandé :

1. D'ajouter une validation stricte des paramètres en entrée (types, bornes,
   valeurs autorisées) avec un message d'erreur utile pour l'agent.
2. D'appliquer le même type de garde-fous de taille si la réponse peut devenir
   volumineuse (limite, troncature, warning clair pour le LLM).
3. D'instrumenter `_log_timing` si le service risque d'être appelé fréquemment
   ou de manière coûteuse.
