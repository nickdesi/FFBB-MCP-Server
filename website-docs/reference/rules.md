# Règles FFBB – Résolution d'équipe, navigation multi-phases et cas limites
## Validé contre MCP FFBB v0.2.0

---

### Outils MCP disponibles et leur rôle réel

| Outil                        | Rôle                                 | Fiabilité multi-équipes        |
|------------------------------|--------------------------------------|--------------------------------|
| `ffbb_search`                | Résolution club → organisme_id       | ✅                             |
| `ffbb_resolve_team`          | Résolution organisme_id uniquement   | ⚠️ Ne résout PAS équipe 1 vs 2 |
| `ffbb_club(action="equipes")`| Liste tous les engagements du club   | ✅ Source de vérité            |
| `ffbb_get(type="poule")`     | Détail complet d'une poule           | ✅ Source de vérité            |
| `ffbb_next_match`            | Prochain match                       | ⚠️ 1 seul engagement retourné  |
| `ffbb_last_result`           | Dernier résultat                     | ⚠️ 1 seul engagement retourné  |
| `ffbb_team_summary`          | Résumé complet équipe                | ⚠️ Même risque                 |
| `ffbb_bilan`                 | Bilan agrégé toutes phases           | ✅ Fiable                      |
| `ffbb_lives`                 | Scores live                          | ✅ Cache 15s                   |

### Cache TTL — impact opérationnel

| Donnée       | TTL     | Conséquence                                              |
|--------------|---------|----------------------------------------------------------|
| Lives        | 15s     | Quasi temps réel                                         |
| Poule        | 15s     | Quasi temps réel                                         |
| Bilan        | 30s     | Quasi temps réel                                         |
| Calendrier   | 30s     | Quasi temps réel                                         |
| Detail/Club  | 86400s  | ⚠️ Nouvelles phases peuvent mettre 24h à apparaître     |
| Search       | 3600s   | ⚠️ Nouveaux clubs pas immédiatement visibles             |

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
- `ffbb_resolve_team` sert UNIQUEMENT à résoudre un organisme_id.
  Il ne reconnaît PAS les labels "U11M1", "U13M2" → retourne `not_found`.
  Ne JAMAIS l'utiliser pour distinguer équipe 1 vs équipe 2.
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

---

### Règle 4 — Filtrer et scorer les engagements

**A. Exclure immédiatement les compétitions parallèles :**
Sauf si l'utilisateur les demande explicitement, ignorer tout engagement
dont le libellé contient :
"Coupe", "Amical", "Brassage", "Tournoi", "Leaders Cup",
"Barrages", "Espoirs", "Coupe de France", "Coupe Territoriale",
"Coupe ARA", "Coupe Allier"

**B. Exclure les phases terminées :**
Si tous les matchs d'une poule ont `joue=1` → phase terminée, exclure.

**C. Scorer les engagements restants (score le plus haut = bon engagement) :**

  Critère phase (libellé compétition) :
  - +30 pts → contient "Phase 3"
  - +20 pts → contient "Phase 2"
  - +10 pts → contient "Phase 1"
  -  +5 pts → aucune mention de phase (engagement initial en cours)

  Critère niveau hiérarchique :
  - +10 pts → "NATIONALE"
  -  +7 pts → "Interrégionale"
  -  +5 pts → "Régionale"
  -  +3 pts → "Départementale"

  Critère sous-division :
  -  -5 pts → contient "Division 6" ou division numérotée haute (indicateur équipe basse)

  Critère numéro d'équipe explicite :
  → Si `numero_equipe` correspond à la demande → SCORE ABSOLU, priorité maximale,
    ignorer tous les autres critères.

**D. En cas d'égalité de score :**
→ Prendre l'engagement avec le `team_id` / `engagement_id` numérique le plus élevé
  (valeur la plus haute = créé en dernier = phase la plus récente).

---

### Règle 5 — Récupérer les matchs sur la bonne poule

`ffbb_get(type="poule", id=poule_id_retenu)`

Filtrer les rencontres :
- `joue = 0` → match non encore joué
- `nomEquipe1` ou `nomEquipe2` contient le nom du club
- Trier par date croissante → premier résultat = prochain match

Si match trouvé avec date dans le passé et `joue=0` :
→ Match probablement reporté ou non encore saisi.
→ Retourner l'information mais signaler que la date peut avoir changé.

Dédupliquer par `match_id` si le même match apparaît dans plusieurs poules.

---

### Règle 6 — Fallback si aucun match à venir dans la poule

→ Descendre au score suivant dans la liste scorée (règle 4C).
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
| Entre deux phases (latence)            | Informer + force_refresh + proposer bilan                   |
| Forfait (score 20-0 ou 0-20)           | Traiter comme match joué, ne pas confondre avec prochain    |
| Poule avec un seul club                | Signaler anomalie, tenter autres engagements                |
| Match reporté (date passée, joue=0)    | Retourner mais signaler date potentiellement incorrecte     |
| Même match dans plusieurs poules       | Dédupliquer par match_id                                    |
| Club récent / nouvel inscrit           | Un seul engagement probable → appliquer règle 2            |
| Fin de saison définitive               | Informer + proposer ffbb_bilan automatiquement              |
| Erreur API / poule vide inattendue     | Tenter engagements suivants, si tout échoue → informer      |
| Données en cache 24h (detail/club)     | Si incohérence suspectée → force_refresh=true               |

---

### Nomenclature des compétitions FFBB

| Préfixe libellé                    | Niveau          | Type              |
|------------------------------------|-----------------|-------------------|
| `Départementale ... - Division X`  | Départemental   | Sous-division     |
| `Départementale ... - Phase N`     | Départemental   | Phase N           |
| `Départementale ...` (sans phase)  | Départemental   | Phase 1 initiale  |
| `Régionale ... - Division X`       | Régional        | Sous-division     |
| `Régionale ... - Phase N`          | Régional        | Phase N           |
| `Régionale ...` (sans phase)       | Régional        | Phase 1 initiale  |
| `Interrégionale ...`               | Interrégional   | Championnat       |
| `NATIONALE ...`                    | National        | Championnat       |
| `RMUxx Brassage` / `Brassage`      | Régional        | Amical/tournoi    |
| `COUPE ...`                        | Toute           | Knockout          |
| `AMICAL ...`                       | Toute           | Hors classement   |
| `BARRAGES ...`                     | Toute           | Promotion/relég.  |
| `LEADERS CUP`                      | National        | Coupe             |
| `ESPOIRS ...`                      | National/Rég.   | Espoirs           |

---

### Arbre de décision — résumé

[0] Demande de score live ? → ffbb_lives d'abord
[1] Résoudre organisme_id → ambigu ? → demander confirmation
[2] ffbb_club(action="equipes", filtre="CatégorieGenre")
      → Aucun résultat ? → élargir le filtre
      → 1 seul engagement actif ? → outils directs (next_match, last_result…)
      → Plusieurs engagements ? → continuer
[3] Exclure Coupes / Brassages / Amicaux / phases terminées
[4] numero_equipe explicite correspond ? → score absolu, utiliser directement
    Sinon → scorer : Phase N (+30/20/10/5) + niveau (+10/7/5/3) + division (-5)
[5] ffbb_get(type="poule", id=meilleur_score)
      → joue=0 avec le club ? OUI → retourner le match le plus proche
      NON → score suivant → retour [5]
[6] Tous épuisés → force_refresh=true → retour [2]
[7] Toujours rien → saison terminée/pause → informer + proposer ffbb_bilan

---

### Implémentation technique — Champs et Casing

**1. Champ `joue` (Match terminé/non-joué)**
- Le système filtre les matchs à venir avec : `if joue not in (0, "0", None):`.
- `0` ou `"0"` indique un match programmé non encore validé par le système live.
- `None` est explicitement inclus pour considérer les matchs sans date ou sans état (`joue=null` dans l'API) comme "non-joués" (ex: matchs reportés sans nouvelle date fixée).

**2. Casing des données (CamelCase vs Snake_case)**
- L'API FFBB et le client v3 utilisent principalement du **camelCase** pour les clés d'objets imbriqués (ex: `idCompetition`, `libellePoule`).
- La fonction `serialize_model` (via `model_dump`) de Pydantic v2 préserve ce casing lors de la conversion en JSON.
- Les services et l'agent doivent privilégier l'accès via les clés d'origine (ex: `obj.get("idCompetition")`) pour garantir la compatibilité avec la source de vérité.
- **Exceptions** : Certains champs de premier niveau (id, nom) peuvent être normalisés par le client, mais les objets `engagements` et `rencontres` conservent les clés FFBB brutes.

---

### Règle 10 — Résolution intelligente (M/F)

Lors de la résolution d'un club par son nom (ex: "Stade Clermontois"), le système applique une logique de filtrage par genre :

1. **Extraction du genre** : Le genre est extrait de la catégorie (ex: "U11M1" -> Masculin, "U13F" -> Féminin).
2. **Filtrage des candidats** :
   - Si l'équipe est **Masculine** : Priorité aux organismes qui NE contiennent PAS "FÉMININ" dans leur nom.
   - Si l'équipe est **Féminine** : Priorité aux organismes qui CONTIENNENT "FÉMININ" (ou équivalent) dans leur nom.
3. **Exception** : Si l'utilisateur fournit le nom complet (ex: "Stade Clermontois Basket Féminin"), ce choix est respecté sans application de la logique M/F.
4. **Persistance** : Une fois l'organisme résolu, son `organisme_id` est réutilisé pour tous les appels suivants tant que le genre reste cohérent.
5. **Transparence en cas d'échec** : Si aucun engagement n'est trouvé après application de cette branche, le système doit lister tous les organismes considérés (en précisant ceux marqués "Féminin") pour validation manuelle.
```
