# 📘 Exemples de Workflows FFBB MCP

Ce document fournit des exemples de bout en bout pour aider les agents IA à suivre les **bons workflows** avec les outils FFBB MCP.

---

## 1. Bilan complet d'une équipe (outil prioritaire `ffbb_bilan`)

**Question utilisateur**  
> "Fais le bilan complet des U13M-1 de l'ASVEL cette saison."

**Workflow attendu côté agent IA**

1. Vérifier que la catégorie est suffisamment précise :
   - Genre : `M` (Masculin) → ok.
   - Numéro d'équipe : `1` → ok (`U13M-1`).
   - Si l'une de ces infos manquait (ex. seulement `U13`), l'agent devrait d'abord demander à l'utilisateur de préciser.

2. Appeler l'outil **prioritaire** :

   - `ffbb_bilan(club_name="ASVEL", categorie="U13M-1")`

   Cet appel retourne le bilan agrégé sur toutes les phases (classement, résultats, statistiques).

3. Construire la réponse structurée :
   - **Bilan total saison** :
     - Nombre de matchs, victoires/défaites/nuls.
     - Points marqués/encaissés, différence.
   - **Détail par phase** :
     - Pour chaque compétition/poule : position, V/D/N, points marqués/encaissés.

4. Ne pas tenter de reconstruire le bilan à partir de `ffbb_get` ou `ffbb_club` si `ffbb_bilan` fournit déjà ces informations.

---

## 2. Calendrier complet d'une équipe via poule (`ffbb_search` → `ffbb_club` → `ffbb_get`)

**Question utilisateur**  
> "Montre moi le calendrier complet des U11F de Limoges."

**Workflow attendu**

1. Désambiguïsation éventuelle :
   - Si le club n'est pas unique (plusieurs clubs "Limoges"), l'agent peut demander de préciser ou choisir le plus probable en expliquant.
   - Vérifier le genre `F` et le niveau (U11F-1, U11F-2, etc.). Si le numéro d'équipe manque, demander.

2. Trouver le club (organisme) :

   - `ffbb_search(type='organismes', query="Limoges")` → récupère un ou plusieurs `organisme_id`.

3. Lister les équipes du club :

   - `ffbb_club(action='equipes', organisme_id=ORGANISME_ID)` → liste des équipes (catégories, genres, numéros d'équipe, poule_id, etc.).

4. Identifier la bonne équipe :
   - Filtrer les équipes U11F.
   - Si plusieurs équipes U11F existent (`U11F-1`, `U11F-2`), utiliser les règles du prompt (prioriser l'équipe 1 ou demander à l'utilisateur de choisir).
   - Récupérer le `poule_id` correspondant.

5. Récupérer le calendrier complet via la poule :

   - `ffbb_get(type='poule', id=POULE_ID)`
   - Cet appel fournit **à la fois le classement et toutes les rencontres** de la poule.

6. Construire la réponse :
   - Lister les matchs (date, heure, domicile/extérieur, adversaire, score si joué).
   - Optionnel : rappeler la position actuelle de l'équipe dans le classement de la poule.

7. **Anti‑pattern à éviter** :
   - Ne pas appeler `ffbb_club(action='calendrier')` tant que le `poule_id` est connu : utiliser `ffbb_get(type='poule')` qui est plus complet et plus précis.

---

## 3. Gestion d'une catégorie ambiguë (désambiguïsation obligatoire)

**Question utilisateur**  
> "Donne moi le classement des U13 de Pau."

**Workflow attendu**

1. Détecter l'ambiguïté :
   - `"U13"` ne précise ni le genre (`M` ou `F`), ni le numéro d'équipe (`-1`, `-2`, ...).

2. Demander une précision à l'utilisateur :

   - Exemple de question :
     > "Peux-tu préciser s'il s'agit de U13M ou U13F, et de quelle équipe (ex. U13M-1, U13M-2) ?"

3. Une fois la catégorie clarifiée (par ex. `U13M-1`), suivre le workflow standard :
   - soit via `ffbb_bilan` si l'objectif est un **bilan complet** sur la saison,
   - soit via le workflow club → poule → `ffbb_get(type='poule')` si l'utilisateur veut spécifiquement le **classement d'une poule**.

4. Ne jamais choisir arbitrairement une équipe en cas d'ambiguïté : la demande d'informations supplémentaires est préférable à une mauvaise hypothèse.

---

## 4. Dernier match d'un club (score uniquement)

**Question utilisateur**  
> "Quel est le score du dernier match des U11M du Stade Clermontois ?"

**Workflow attendu**

1. Trouver le club (organisme) :
   - `ffbb_search(type='organismes', query="Stade Clermontois")` → récupérer l'`organisme_id`.

2. Récupérer un calendrier court pour la catégorie ciblée :
   - `ffbb_club(action="calendrier", organisme_id=<ID>, filtre="U11M")`
   - La réponse contient une liste de matchs avec, pour chacun : `played`, `is_last_match`, `is_next_match`, `score_equipe1`, `score_equipe2`, etc.

3. Identifier le dernier match joué :
   - filtrer le tableau sur `is_last_match == true` ;
   - retourner ce match et son score pour répondre à la question.

4. Explication importante :
   - ne pas utiliser `ffbb_get(type='poule')` dans ce cas, car la poule contient souvent ~100 matchs et la réponse est tronquée côté MCP ;
   - le dernier match du club pourrait se trouver dans la partie tronquée ;
   - réserver `ffbb_get(type='poule')` aux cas où l'utilisateur demande explicitement le **classement complet** ou l'**historique entier** de la poule.

---

## 5. Recettes utilisateur

### Parent — “Quand et où joue l’équipe ?”

- Question typique : “C’est quand le prochain match des U13M1 ?”
- Outil recommandé : `ffbb_next_match`.
- Si la catégorie est incomplète (`U13M` sans numéro), appeler d’abord `ffbb_resolve_team`.
- Réponse attendue : date, heure, salle, domicile/extérieur, adversaire.

### Coach — “Quels matchs restent à jouer ?”

- Question typique : “Combien de matchs restent aux U15F ?”
- Outil obligatoire : `ffbb_club(action="calendrier")`.
- Filtrer côté agent : `played == false`, puis trier par date croissante.
- Ne pas utiliser `ffbb_next_match`, qui ne retourne qu’une seule échéance.

### Journaliste — “Bilan et dynamique d’une équipe”

- Question typique : “Quel est le bilan des U18M1 cette saison ?”
- Outil recommandé : `ffbb_team_summary` pour une synthèse rapide, ou `ffbb_bilan` pour le détail toutes phases.
- Réponse attendue : bilan total, phase courante, dernier résultat, prochain match.

### Club / administrateur — “Programme d’une catégorie”

- Question typique : “Donne le programme U11 du club ce week-end.”
- Workflow : résoudre le club une fois avec `ffbb_search(type="organismes")`, mémoriser l’`organisme_id` dans la conversation, puis appeler `ffbb_club(action="calendrier", filtre="U11")`.
- Réponse attendue : liste compacte par équipe, horaire et lieu.

### Développeur agent — “Éviter les mauvaises hypothèses”

- Si une catégorie est ambiguë (`U13`, `U13M`) : appeler `ffbb_resolve_team`.
- Si la demande est au pluriel : appeler `ffbb_club(action="calendrier")`.
- Si l’utilisateur donne un nom plutôt qu’un ID : résoudre avec `ffbb_search`, puis réutiliser l’`organisme_id`.

---

## 6. Notes générales pour les agents

- Utiliser `ffbb_search(type="organismes")` pour lever une ambiguïté de club, puis réutiliser l'`organisme_id`.
- Utiliser `ffbb_club(action="equipes")` pour lister les engagements, phases et `poule_id` disponibles d'un club.
- Utiliser `ffbb_resolve_team` quand la catégorie ou le numéro d'équipe est ambigu (`U11M`, `U13F2`, etc.).
- Utiliser `ffbb_team_summary` pour obtenir en un appel un résumé équipe + dernier/prochain match + bilan.
- Utiliser `ffbb_bilan` ou `ffbb_bilan_saison` pour un bilan complet de saison.
- Utiliser `ffbb_get(type="poule")` pour une demande sur la poule complète : classement, historique et calendrier global.
- Utiliser `ffbb_club(action="calendrier")` pour une liste de matchs filtrée club/équipe/catégorie avec `is_last_match` et `is_next_match`.
- Utiliser `ffbb_last_result` et `ffbb_next_match` pour les questions directes au singulier : “dernier résultat” ou “prochain match”.
- Demander une précision à l'utilisateur si plusieurs clubs, équipes, phases ou poules correspondent.
