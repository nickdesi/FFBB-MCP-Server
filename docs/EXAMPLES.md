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

## 2. Calendrier complet d'une équipe via `ffbb_club(action="calendrier")`

**Question utilisateur**  
> "Montre moi le calendrier complet des U11F de Limoges."

**Workflow attendu**

1. Désambiguïsation éventuelle :
   - Si le club n'est pas unique (plusieurs clubs "Limoges"), résoudre via `ffbb_search(type='organismes')`.
   - Vérifier le genre `F` et le niveau (U11F-1, U11F-2, etc.). Si le numéro d'équipe manque et que plusieurs équipes existent, utiliser `ffbb_resolve_team` ou demander.

2. Trouver le club (organisme) :

   - `ffbb_search(type='organismes', query="Limoges")` → récupère un ou plusieurs `organisme_id`.

3. Récupérer le calendrier exhaustif filtré :

   - `ffbb_club(action='calendrier', organisme_id=ORGANISME_ID, filtre="U11F", numero_equipe=1)`

4. Construire la réponse :
   - Lister les matchs (date, heure, domicile/extérieur, adversaire, score si joué).
   - Pour des **matchs restants**, garder uniquement `played == false`, puis trier par date croissante.
   - Si la réponse contient une métadonnée `_meta.generated_at`, l'utiliser pour qualifier la fraîcheur des données si utile.

5. **Anti-pattern à éviter** :
   - Ne pas appeler `ffbb_next_match` pour une demande au pluriel ou un calendrier complet.
   - Ne pas s'appuyer uniquement sur `ffbb_get(type='poule')` pour des matchs restants : la poule peut être tronquée.

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

2. Résoudre l'équipe si nécessaire :
   - `ffbb_resolve_team(organisme_id=<ID>, categorie="U11M")` si plusieurs équipes U11M peuvent exister.

3. Appeler l'outil singulier :
   - `ffbb_last_result(organisme_id=<ID>, categorie="U11M", numero_equipe=1)`

4. Répondre avec le tableau domicile/extérieur et le score.

5. Explication importante :
   - `ffbb_last_result` est le bon outil pour un **dernier match** au singulier ;
   - utiliser `ffbb_club(action="calendrier")` seulement si l'utilisateur demande plusieurs résultats ou le calendrier.

---

## 5. Matchs restants d'une équipe

**Question utilisateur**
> "Combien de matchs restent-ils aux U13M1 du Stade Clermontois ?"

**Workflow attendu**

1. Résoudre le club :
   - `ffbb_search(type='organismes', query="Stade Clermontois")` → `organisme_id`.

2. Identifier l'équipe si nécessaire :
   - `ffbb_team_summary(organisme_id=<ID>, categorie="U13M1")` pour récupérer le contexte équipe et la phase courante.

3. Récupérer le calendrier complet du club filtré :
   - `ffbb_club(action="calendrier", organisme_id=<ID>, filtre="U13M", numero_equipe=1)`

4. Filtrer côté agent :
   - garder uniquement `played == false` ;
   - trier par date croissante ;
   - compter les matchs restants ;
   - déterminer domicile/déplacement avec `equipe1` = domicile et `equipe2` = extérieur.

5. Répondre avec le nombre total et les prochaines échéances, sans afficher le calendrier brut complet.

---

## 6. Notes générales pour les agents

- Utiliser `ffbb_search(type="organismes")` pour lever une ambiguïté de club, puis réutiliser l'`organisme_id`.
- Utiliser `ffbb_club(action="equipes")` pour lister les engagements, phases et `poule_id` disponibles d'un club.
- Utiliser `ffbb_resolve_team` quand la catégorie ou le numéro d'équipe est ambigu (`U11M`, `U13F2`, etc.).
- Utiliser `ffbb_team_summary` pour obtenir en un appel un résumé équipe + dernier/prochain match + bilan.
- Utiliser `ffbb_bilan` ou `ffbb_bilan_saison` pour un bilan complet de saison.
- Utiliser `ffbb_get(type="poule")` pour une demande sur la poule complète : classement, historique et calendrier global.
- Utiliser `ffbb_club(action="calendrier")` pour une liste de matchs filtrée club/équipe/catégorie avec `is_last_match` et `is_next_match`.
- Pour les matchs restants ou prochaines journées, filtrer `played == false` et trier par date croissante.
- Si `_meta.generated_at`, `_meta.timezone` ou `_meta.cache` est présent, s'en servir pour qualifier la fraîcheur sans polluer la réponse.
