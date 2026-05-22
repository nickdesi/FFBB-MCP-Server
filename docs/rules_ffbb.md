# 🏀 Règles métier FFBB MCP

> Validé contre MCP FFBB v1.2.0 et champs exposés par `ffbb-data-client`

---

### Outils MCP disponibles et leur rôle réel

| Outil                        | Rôle                                       | Fiabilité multi-équipes        |
|------------------------------|--------------------------------------------|--------------------------------|
| `ffbb_search`                | Résolution club → organisme_id             | ✅                             |
| `ffbb_resolve_team`          | Résolution club + catégorie + numéro si possible | ⚠️ Peut rester ambigu si plusieurs équipes/phases |
| `ffbb_club(action="equipes")`| Liste tous les engagements du club         | ✅ Source de vérité            |
| `ffbb_get(type="poule")`     | Détail complet d'une poule           | ✅ Source de vérité            |
| `ffbb_next_match`            | Prochain match                       | ⚠️ 1 seul engagement retourné  |
| `ffbb_last_result`           | Dernier résultat                     | ⚠️ 1 seul engagement retourné  |
| `ffbb_team_summary`          | Résumé complet équipe                | ⚠️ Même risque                 |
| `ffbb_bilan`                 | Bilan agrégé toutes phases           | ✅ Fiable                      |
| `ffbb_lives`                 | Scores live                          | ✅ Cache 15s                   |

### Cache TTL — impact opérationnel

Les TTL sont **dynamiques** et s'adaptent aux fenêtres horaires de match (mercredi 13h-20h, vendredi 18h-23h, samedi 8h-21h, dimanche 8h-21h) :

| Donnée       | TTL hors match        | TTL en fenêtre live | Conséquence                                              |
|--------------|-----------------------|---------------------|----------------------------------------------------------|
| Lives        | 15s                   | 15s                 | Quasi temps réel                                         |
| Poule        | 86400s (24h)          | 5s à 1800s          | Dynamique : 15s si match live dans la poule, 300s en fenêtre WE, 1800s post-match, 24h sinon |
| Bilan        | 86400s (24h)          | 1800s (30min)       | Rafraîchi toutes les 30min les jours de match            |
| Classement   | 86400s (24h)          | 1800s (30min)       | Rafraîchi toutes les 30min les jours de match            |
| Calendrier   | 86400s (24h)          | 300s à 1800s        | 300s (5min) en fenêtre live, 1800s (30min) post-match, 24h sinon |
| Organisme    | 86400s (24h)          | 86400s (24h)        | ⚠️ Nouvelles phases peuvent mettre 24h à apparaître     |
| Search       | 86400s (24h)          | 86400s (24h)        | ⚠️ Nouveaux clubs pas immédiatement visibles             |

---

### Règle 0 — Score live d'abord

Si l'utilisateur demande un score "maintenant" ou "en ce moment" :
→ Appeler `ffbb_lives` EN PREMIER.
→ Si retourne [] → aucun match en cours, continuer workflow normal.

---

### Règle 1 — Résolution du club

- Utiliser `ffbb_search(type="organismes", query="nom_club")` ou
  laisser `ffbb_next_match` / `ffbb_resolve_team` résoudre automatiquement.
- Si `status: "ambiguous"` → présenter les candidats à l'utilisateur
  et attendre confirmation avant de continuer.
- `ffbb_resolve_team` peut résoudre une équipe unique quand la catégorie et le
  `numero_equipe` sont suffisamment clairs. En revanche, pour inspecter toutes
  les phases, poules et engagements, `ffbb_club(action="equipes")` reste la
  source de vérité.
- Mémoriser l'`organisme_id` résolu pour tous les appels suivants.

---

### Règle 2 — Cas simple (club avec une seule équipe dans la catégorie)

Avant tout workflow complexe, vérifier via `ffbb_club(action="equipes")` :
→ Si UN SEUL engagement actif dans la catégorie demandée :
  → Utiliser `ffbb_next_match` / `ffbb_last_result` / `ffbb_team_summary`
     directement. Pas besoin du workflow complet.
→ Si PLUSIEURS engagements → workflow complet obligatoire (règles 3 à 7).

---

### Règle 3 — Lister tous les engagements

`ffbb_club(action="equipes", organisme_id=X, filtre="U13M")`

- Si le filtre retourne rien → essayer sans genre ("U13"),
  puis sans filtre et filtrer manuellement sur `categorie` + `sexe`.
- Si catégorie sans genre précisé (ex: "U11") → retourner les deux genres
  et demander confirmation à l'utilisateur.
- Si le genre est connu mais le numéro d'équipe est absent (ex: "U11M") :
  → ne pas demander confirmation immédiatement ; appliquer la règle 4 sans
    score absolu sur `numero_equipe`.

---

### Règle 4 — Filtrer et scorer les engagements

**A. Exclure ou déprioriser les compétitions parallèles :**
Sauf si l'utilisateur les demande explicitement, ignorer les compétitions
clairement parallèles au championnat.

Priorité de détection :
1. Si un champ API fiable existe (`typeCompetition`, `natureCompetition`,
   `competitionType` ou équivalent), l'utiliser en priorité.
2. Sinon, appliquer un filtre heuristique sur le libellé contenant :
   "Coupe", "Amical", "Tournoi", "Leaders Cup", "Coupe de France",
   "Coupe Territoriale", "Coupe ARA", "Coupe Allier".

Ne pas exclure automatiquement `Brassage`, `Qualification` ou `Barrages` :
ces libellés peuvent représenter une phase officielle FFBB active. Les traiter
comme candidats valides si l'utilisateur les demande, s'ils sont la seule phase
active, ou si aucune phase de championnat plus récente n'a de match à venir.

Ne pas exclure ces compétitions si l'utilisateur demande explicitement
une coupe, un tournoi, une compétition parallèle ou un bilan complet.

**B. Exclure les phases terminées :**
Si la sortie locale fournit `rencontres_restantes_par_equipe`, l'utiliser en
priorité : une phase n'est terminée pour l'équipe cible que si cette équipe n'a
plus de rencontre à venir.

À défaut, si tous les matchs d'une poule ont `joue=1`, considérer la poule comme
terminée. Ne pas conclure uniquement depuis le classement ou le nombre de matchs
joués.

Si les seuls matchs restants ont `joue=null` ou une date passée depuis plus
de 30 jours, considérer la phase comme probablement inactive/terminée,
sauf indice contraire dans les données.

**C. Score absolu sur numéro d'équipe explicite :**
Avant tout scoring pondéré, si la demande contient un `numero_equipe` explicite
et qu'un engagement correspondant existe :
→ utiliser cet engagement en priorité maximale ;
→ ignorer les critères de phase, niveau et division pour ce choix.

**D. Scorer les engagements restants (score le plus haut = bon engagement) :**

  Critère phase (libellé compétition) :
  - +35 pts → contient "Phase 3" ou "3EME PHASE"
  - +25 pts → contient "Phase 2", "2EME PHASE", "Poule Haute", "Titre", "Play-off" ou "Final Four"
  - +15 pts → contient "Phase 1", "1ERE PHASE", "Qualification", "Brassage", "Pré-région", "Préregion"
  - +10 pts → contient "Poule Basse", "Maintien", "Excellence", "Honneur" ou "Promotion"
  -  +5 pts → aucune mention de phase (engagement initial en cours)

  Critère niveau hiérarchique :
  - +10 pts → "NATIONALE", `NM1`, `NM2`, `NM3`, `NF1`, `NF2`, `NF3`
  -  +7 pts → "Interrégionale"
  -  +5 pts → "Régionale", `RM1`, `RM2`, `RM3`, `RF1`, `RF2`, `RF3`
  -  +3 pts → "Départementale", `PRM`, `PRF`, `DM1`, `DM2`, `DM3`, `DF1`, `DF2`, `DF3`

  Critère sous-division :
  -  -2 pts → contient "Division 6" ou division numérotée haute. C'est un signal faible seulement : ne jamais l'utiliser contre un `numero_equipe` explicite ou une poule active future.

**E. En cas d'égalité de score :**
→ Prendre l'engagement avec le `team_id` / `engagement_id` numérique le plus élevé
  (valeur la plus haute = créé en dernier = phase la plus récente).

---

### Règle 5 — Récupérer les matchs sur la bonne poule

`ffbb_get(type="poule", id=poule_id_retenu)`

Filtrer les rencontres :
- `joue = 0` ou `joue = "0"` → match non encore joué
- `joue = null` → match à considérer comme non joué si aucune autre information ne l'invalide
- Identifier le club dans la rencontre avec cette priorité :
  1. `idEngagementEquipe1` / `idEngagementEquipe2` en comparant leur `id` avec l'`engagement_id` retenu ;
  2. `idOrganismeEquipe1` / `idOrganismeEquipe2` en comparant leur `id` avec l'`organisme_id`, si l'engagement n'est pas disponible ;
  3. nom d'équipe normalisé (`nomEquipe1`, `nomEquipe2`) avec casse, accents, espaces, abréviations, `CTC`, `ENT.`, `Entente` et `Union` ;
  4. `nomEquipe1` ou `nomEquipe2` contient le nom du club en dernier recours.
- Trier par date croissante → premier résultat = prochain match

Si match trouvé avec date dans le passé et `joue=0` :
→ Match probablement reporté ou non encore saisi.
→ Retourner l'information mais signaler que la date peut avoir changé.

Dédupliquer par `match_id` si le même match apparaît dans plusieurs poules.

---

### Règle 6 — Fallback si aucun match à venir dans la poule

→ Descendre au score suivant dans la liste scorée (règle 4D).
→ Répéter la règle 5 sur cette nouvelle poule.
→ Continuer jusqu'à trouver un match ou épuiser tous les engagements.

Si tous les engagements sont épuisés sans résultat :
→ Suspecter un engagement de nouvelle phase non encore mis en cache.
→ Relancer avec `force_refresh=true` :
   `ffbb_club(action="equipes", force_refresh=true)`
   `ffbb_get(type="poule", force_refresh=true)`
→ Si toujours rien → appliquer la règle 7.

---

### Règle 7 — Fallback final (fin de saison ou pause)

Informer l'utilisateur :
- Saison terminée pour cette équipe, OU
- Entre deux phases (latence normale de quelques jours à quelques semaines), OU
- Données FFBB non encore disponibles.

Si la dernière date de match connue est disponible, l'afficher pour contextualiser
la fin de phase ou la pause.

Proposer automatiquement :
→ `ffbb_bilan` pour consulter le bilan complet de la saison.

---

### Règle 8 — Bilan et dernier résultat

Pour toute demande de bilan global :
→ Utiliser `ffbb_bilan` en priorité (TTL 30s, agrège toutes les phases).
→ Ne PAS reconstruire manuellement un bilan depuis les poules individuelles.

Pour le dernier résultat :
→ Si club mono-équipe dans la catégorie → `ffbb_last_result` directement.
→ Si multi-engagements → appliquer règles 3+4 pour identifier la bonne poule,
   puis `ffbb_get(type="poule")` et filtrer `joue=1` + date la plus récente.

---

### Règle 9 — Gestion des cas limites

| Cas                                    | Action                                                      |
|----------------------------------------|-------------------------------------------------------------|
| Club ambigu                            | Demander confirmation utilisateur avant de continuer        |
| Catégorie sans genre (ex: "U11")       | Demander confirmation M ou F                                |
| Genre connu sans numéro équipe         | Appliquer scoring règle 4 sans score absolu                 |
| CTC / Entente / Union                  | Identifier par engagement_id d'abord, nom normalisé ensuite |
| Entre deux phases (latence)            | Informer + force_refresh + proposer bilan                   |
| Score 20-0/0-20                        | Indice de forfait seulement ; confirmer via `joue=1` et statut/motif si disponible |
| Poule avec un seul club                | Signaler anomalie, tenter autres engagements                |
| Match reporté (date passée, joue=0)    | Retourner mais signaler date potentiellement incorrecte     |
| Même match dans plusieurs poules       | Dédupliquer par match_id                                    |
| Club récent / nouvel inscrit           | Un seul engagement probable → appliquer règle 2            |
| Fin de saison définitive               | Informer + proposer ffbb_bilan automatiquement              |
| Erreur API / poule vide inattendue     | Tenter engagements suivants, si tout échoue → informer      |
| Données en cache 24h (detail/club)     | Si incohérence suspectée → force_refresh=true               |

---

### Nomenclature des compétitions FFBB

| Préfixe / libellé                  | Niveau          | Type / interprétation |
|------------------------------------|-----------------|-----------------------|
| `SM`, `SF`                         | Senior          | Senior masculin/féminin |
| `PRM`, `PRF`                       | Pré-régional / départemental haut | Championnat |
| `DM1`, `DM2`, `DM3`, `DF1`, `DF2`, `DF3` | Départemental | Divisions seniors |
| `RM1`, `RM2`, `RM3`, `RF1`, `RF2`, `RF3` | Régional | Divisions régionales |
| `NM1`, `NM2`, `NM3`, `NF1`, `NF2`, `NF3` | National | Championnat national |
| `Départementale ... - Division X`  | Départemental   | Sous-division         |
| `Départementale ... - Phase N`     | Départemental   | Phase N               |
| `Départementale ...` (sans phase)  | Départemental   | Phase 1 initiale      |
| `Régionale ... - Division X`       | Régional        | Sous-division         |
| `Régionale ... - Phase N`          | Régional        | Phase N               |
| `Régionale ...` (sans phase)       | Régional        | Phase 1 initiale      |
| `Interrégionale ...`               | Interrégional   | Championnat           |
| `NATIONALE ...`                    | National        | Championnat           |
| `1ERE PHASE` / `2EME PHASE` / `Phase N` | Toute      | Phase chronologique   |
| `POULE HAUTE` / `POULE BASSE`      | Toute           | Reclassement          |
| `TITRE` / `MAINTIEN`               | Toute           | Phase finale / maintien |
| `QUALIFICATION` / `BRASSAGE`       | Toute           | Phase officielle possible, pas hors-compétition par défaut |
| `EXCELLENCE` / `HONNEUR` / `PROMOTION` | Dép./Rég.   | Niveaux territoriaux  |
| `PLAY-OFF` / `FINAL FOUR`          | Toute           | Phase finale          |
| `CTC`, `ENT.`, `Entente`, `Union`  | Toute           | Regroupement de clubs ; matcher par engagement avant le nom |
| `COUPE ...`                        | Toute           | Knockout / parallèle  |
| `AMICAL ...`                       | Toute           | Hors classement       |
| `BARRAGES ...`                     | Toute           | Promotion/relég. ; phase officielle possible |
| `LEADERS CUP`                      | National        | Coupe                 |
| `ESPOIRS ...`                      | National/Rég.   | Espoirs               |

---

### Arbre de décision — résumé

[0] Demande de score live ? → ffbb_lives d'abord
[1] Résoudre organisme_id → ambigu ? → demander confirmation
[2] ffbb_club(action="equipes", filtre="CatégorieGenre")
      → Aucun résultat ? → élargir le filtre
      → Catégorie sans genre ? → demander M/F
      → Genre connu sans numéro équipe ? → continuer sans score absolu
      → 1 seul engagement actif ? → outils directs (next_match, last_result…)
      → Plusieurs engagements ? → continuer
[3] Exclure Coupes / Amicaux / Tournois ; garder Brassage/Qualification/Barrages si phase officielle active
[4] numero_equipe explicite correspond ? → court-circuit, utiliser directement
    Sinon → scorer : Phase/libellé (+35/25/15/10/5) + niveau (+10/7/5/3) + division faible (-2)
[5] ffbb_get(type="poule", id=meilleur_score)
      → engagement_id trouvé via idEngagementEquipe1/2 et joue=0 ? OUI → retourner le match le plus proche
      NON → score suivant → retour [5]
[6] Tous épuisés → force_refresh=true → retour [2]
[7] Toujours rien → saison terminée/pause → informer + proposer ffbb_bilan

---

### Implémentation technique — Champs et Casing

**1. Champ `joue` (Match terminé/non-joué)**
- Le système filtre les matchs à venir avec : `if joue not in (0, "0", None):`.
- `0` ou `"0"` indique un match programmé non encore validé par le système live.
- `None` est explicitement inclus pour considérer les matchs sans date ou sans état (`joue=null` dans l'API) comme "non-joués" (ex: matchs reportés sans nouvelle date fixée).

**2. Champs fiables côté `ffbb-data-client`**
- Engagements club : `engagements.id`, `engagements.numeroEquipe`, `engagements.idCompetition.id`, `engagements.idCompetition.nom`, `engagements.idCompetition.code`, `engagements.idPoule.id`, `engagements.idCompetition.sexe`.
- Rencontres/poules : `rencontres.joue`, `rencontres.nomEquipe1`, `rencontres.nomEquipe2`, `rencontres.resultatEquipe1`, `rencontres.resultatEquipe2`, `rencontres.date_rencontre`, `rencontres.numeroJournee`, `rencontres.idEngagementEquipe1`, `rencontres.idEngagementEquipe2`, `rencontres.idOrganismeEquipe1`, `rencontres.idOrganismeEquipe2`.
- Ne pas utiliser `idEquipe1` / `idEquipe2` comme champs de référence : les champs validés sont `idEngagementEquipe1` / `idEngagementEquipe2`.

**3. Champs normalisés par le MCP local**
- `ffbb_club(action="equipes")` expose notamment `team_id`, `engagement_id`, `numero_equipe`, `team_label`, `phase_label`, `nom_equipe`, `competition`, `competition_id`, `poule_id`, `sexe`, `categorie`, `niveau`.
- `numeroEquipe` est le champ brut API ; `numero_equipe` est l'alias normalisé local.
- Quand `ffbb_get(type="poule")` enrichit la réponse, `rencontres_restantes_par_equipe` et `phase_terminee` doivent être privilégiés pour juger une phase active/terminée.

**4. Casing des données (CamelCase vs Snake_case)**
- L'API FFBB et le client v3 utilisent principalement du **camelCase** pour les clés d'objets imbriqués (ex: `idCompetition`, `libellePoule`, `idEngagementEquipe1`).
- La fonction `serialize_model` (via `model_dump`) de Pydantic v2 préserve ce casing lors de la conversion en JSON.
- Si `model_dump(by_alias=True)` est utilisé, les alias Pydantic peuvent modifier les noms de clés retournés ; vérifier alors le casing réel dans la sortie sérialisée.
- Les services et l'agent doivent privilégier l'accès via les clés d'origine (ex: `obj.get("idCompetition")`) pour garantir la compatibilité avec la source de vérité.
- **Exceptions** : Certains champs de premier niveau (id, nom) peuvent être normalisés par le client, mais les objets `engagements` et `rencontres` conservent les clés FFBB brutes.

---

### Règle 10 — Résolution intelligente (M/F)

Lors de la résolution d'un club par son nom (ex: "Stade Clermontois"), le système applique une logique de priorisation par genre :

1. **Extraction du genre** : Le genre est extrait de la catégorie (ex: "U11M1" -> Masculin, "U13F" -> Féminin).
2. **Priorisation des candidats** :
   - Si l'équipe est **Masculine** : Priorité aux organismes qui NE contiennent PAS "FÉMININ" dans leur nom.
   - Si l'équipe est **Féminine** : Priorité aux organismes qui CONTIENNENT "FÉMININ" (ou équivalent) dans leur nom.
3. **Heuristique non exclusive** : Cette logique sert à trier les candidats, jamais à exclure définitivement un organisme. Les clubs mixtes peuvent porter les équipes masculines et féminines dans le même organisme.
4. **Fallback** : Si aucun engagement n'est trouvé après priorisation M/F, relancer sur l'ensemble des organismes candidats sans filtre de genre sur le nom.
5. **Exception** : Si l'utilisateur fournit le nom complet (ex: "Stade Clermontois Basket Féminin"), ce choix est respecté sans application de la logique M/F.
6. **Persistance** : Une fois l'organisme résolu, son `organisme_id` est réutilisé pour tous les appels suivants tant que le genre reste cohérent.
7. **Transparence en cas d'échec** : Si aucun engagement n'est trouvé après fallback, le système doit lister tous les organismes considérés (en précisant ceux marqués "Féminin") pour validation manuelle.
