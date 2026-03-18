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

## 4. Notes générales pour les agents IA

- Toujours privilégier les **outils unifiés** (`ffbb_bilan`, `ffbb_search`, `ffbb_get`, `ffbb_club`, `ffbb_lives`, `ffbb_saisons`) plutôt qu'une combinaison ad hoc d'appels bas niveau.
- Garder en tête que les données FFBB sont **live** :
  - appeler les outils dès que des informations fraîches (score, classement, calendrier) sont nécessaires ;
  - ne pas s'appuyer sur des suppositions ou sur des informations mémorisées dans la conversation.
- Répéter un appel avec les mêmes paramètres est acceptable : le serveur MCP applique un cache interne pour limiter la charge sur l'API officielle FFBB.
