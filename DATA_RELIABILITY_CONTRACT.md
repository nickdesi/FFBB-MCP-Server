# CONTRAT DE FIABILITÉ DES DONNÉES (DATA RELIABILITY CONTRACT)
## Serveur FFBB MCP — Version 1.15.0+

---

## 1. Principe Fondateur Non Négociable

> **« Il vaut toujours mieux retourner `ambiguous`, `not_found`, `partial`, `stale` ou `unknown_conflict` plutôt qu'une donnée sportive vraisemblable mais potentiellement fausse. »**

Le serveur **FFBB MCP** s'interdit formellement :
- d'inventer ou de deviner des scores, horaires, lieux ou statuts non confirmés ;
- de masquer une ambiguïté réelle sous un choix arbitraire ;
- de mélanger des équipes de catégories ou de sexes distincts (ex: NM3 vs PNM, U15M vs U15F, équipe 1 vs équipe réserve) ;
- d'extrapoler des confrontations directes (H2H) sans lien formel d'engagements ou de poule ;
- d'agréger des rencontres présentant des anomalies critiques ou des scores contradictoires dans les statistiques sportives officielles (bilan, classement, dynamique).

---

## 2. Machine à États Canonique des Rencontres (`CanonicalMatchStatus`)

Chaque match issu des API ou de l'open data FFBB est normalisé à travers une machine à états canonique déterministe.

### 2.1. États Canoniques Autorisés

| Statut Canonique | Description | Éligible aux Agrégats Sportifs ? |
| :--- | :--- | :---: |
| `scheduled` | Rencontre programmée dans le calendrier officiel | ❌ Non |
| `live` | Rencontre en cours de jeu | ❌ Non |
| `halftime` | Mi-temps | ❌ Non |
| `overtime` | Prolongation en cours | ❌ Non |
| `final` | Rencontre terminée avec score validé | ✅ **Oui** |
| `postponed` | Rencontre officiellement reportée | ❌ Non |
| `cancelled` | Rencontre annulée définitivement | ❌ Non |
| `forfeit_home` | Forfait équipe domicile (homologué 0-20 ou 0-0) | ✅ **Oui** (comptable) |
| `forfeit_away` | Forfait équipe extérieur (homologué 20-0 ou 0-0) | ✅ **Oui** (comptable) |
| `forfeit_both` | Double forfait (homologué 0-0) | ✅ **Oui** (comptable) |
| `unknown_conflict` | **Anomalie ou contradiction détectée** | ❌ **Strictement Interdit** |

### 2.2. Règle de Détection des Conflits Stricts

Une rencontre est automatiquement disqualifiée en `unknown_conflict` (niveau de qualité `conflict`) dès qu'elle présente l'une des incohérences suivantes :
1. **Scheduled vs Scores Réels** : Statut brut déclaré "PROGRAMME" / "NON COMMENCE" mais scores strictement positifs déjà saisis.
2. **Played vs Absence de Score** : Statut brut déclaré "TERMINE" / "JOUE" mais aucun score ni résultat renseigné.
3. **Live vs Complete** : Statut brut déclaré "EN COURS" alors que le flag d'état final est actif.
4. **Dates Impossibles** : Date/heure de match syntaxiquement invalide ou non parsable.
5. **Forfait Incohérent** : Forfait déclaré mais score incompatible avec les règles fédérales (ni 20-0, ni 0-20, ni 0-0).
6. **Annulé avec Score Positif** : Match déclaré annulé mais présentant un score strictement positif.
7. **Score Nul en Basket Officiel** : Score d'égalité à la fin du temps réglementaire sans prolongation enregistrée dans une compétition officielle.

Tout match en `unknown_conflict` est **exclu par défaut des calendriers et bilans**, sauf demande explicite du consommateur via le drapeau `include_conflicts=True`.

---

## 3. Résolution d'Équipe et Anti-Ambiguïté (`strict_resolver`)

### 3.1. Hiérarchie de Résolution en 6 Paliers Déterministes

Pour éliminer tout risque d'homonymie ou d'association erronée, la résolution d'équipe applique strictement la priorité suivante :

```
[1] engagement_id explicite (100% déterministe)
       ↓ (si absent)
[2] club_name / organisme_id + division canonique univoque
       ↓ (si absent)
[3] Catégorie + Sexe normalisés (ex: "U18M", "SEF")
       ↓ (si absent)
[4] Numéro d'équipe strict (1, 2, 3...)
       ↓ (si absent)
[5] Type de compétition (Championnat vs Coupe vs Tournoi)
       ↓ (si absent)
[6] Phase la plus récente de la même équipe
```

### 3.2. Règles d'Arbitrage Sans Fallback Silencieux

1. **Rejet de Genre et Niveau** : Une requête pour `NM3` (Nationale Masculine 3) ne se rabat **JAMAIS** sur `PNM` (Prénationale Masculine). Une requête pour `U15M` ne se rabat **JAMAIS** sur `U15F`.
2. **Déclaration d'Ambiguïté Immédiate** : Si un club possède plusieurs équipes éligibles (ex: équipe 1 en PNM et équipe 2 en DM2), le serveur retourne immédiatement :
   ```json
   {
     "status": "ambiguous",
     "team": null,
     "candidates": [...],
     "clarification_prompt": "L'équipe possède plusieurs engagements distincts. Précisez `competition_id`, `competition_type` ou `numero_equipe`."
   }
   ```
3. **Distinction entre Phases et Ambiguïté** : La progression d'une même équipe à travers plusieurs phases successives (Phase 1, Phase 2, Play-offs) au cours d'une même saison ne constitue pas une ambiguïté. Le résolveur retient automatiquement la phase la plus avancée tout en documentant la traçabilité.

---

## 4. Scoping Strict du Calendrier (`scope=team|club|competition`)

Le service de calendrier refuse tout élargissement silencieux qui noierait une équipe spécifique dans l'ensemble des matchs de son club.

- **`scope="team"` (défaut si catégorie ou numéro spécifié)** :
  - Restitue uniquement les rencontres de l'équipe ciblée.
  - Exclusion stricte des matchs des autres catégories du club.
  - Exclusion stricte des matchs amicaux (`PLAT`, `AMIC`), tournois et plateaux non officiels par défaut (`include_friendlies=False`).
  - Exclusion des coupes si une division de championnat régulière est visée, sauf accord explicite.
  - Exclusion des réserves (équipe 2, 3) par défaut (`include_reserves=False`).
  - Si l'équipe ciblée n'a aucun match, le serveur retourne un statut `not_found` explicite avec avertissement d'absence d'élargissement.
- **`scope="club"`** :
  - Restitue les rencontres de l'ensemble des équipes engagées du club.
- **`scope="competition"`** :
  - Restitue l'ensemble des rencontres de la poule ou de la division ciblée.

---

## 5. Règlements et Hiérarchie des Normes Juridiques

Le moteur réglementaire (`RegulationsEngine`) indexe les textes officiels avec garantie d'intégrité cryptographique SHA-256.

### 5.1. Ordre de Primauté Juridique

Lorsqu'un litige ou une règle d'application est interrogé :
1. **Règlement Fédéral FFBB (Niveau 1 — Primauté Absolue)** : Statuts et Règlements Généraux de la FFBB.
2. **Règlement Régional (Niveau 2)** : Règlements particuliers des Ligues Régionales.
3. **Règlement Départemental (Niveau 3)** : Règlements des Comités Départementaux.

En cas de divergence, la disposition supérieure prévaut sauf délégation expresse prévue par le texte fédéral.

### 5.2. Mentions Légales et Avertissements Obligatoires

Chaque consultation réglementaire génère systématiquement :
- L'empreinte cryptographique `sha256_hash` du texte source.
- La date de dernière mise à jour officielle.
- La clause de non-opposabilité juridique :
  > *« Information réglementaire indicative issue des documents indexés. Pour une décision officielle, vérifier le règlement applicable de la saison, les éventuelles dispositions territoriales et la commission compétente. »*
- Si le règlement local (comité/ligue) n'est pas indexé, un avertissement explicite est obligatoirement adjoint :
  > *« Règlement local non indexé : vérification nécessaire auprès de l'organisateur. »*

---

## 6. Observabilité, Télémétrie et Métriques de Fiabilité

Le serveur expose des métriques Prometheus dédiées à la mesure de la qualité des données sur `/metrics` :

- `ffbb_reliability_ambiguous_total` : Nombre total de requêtes ayant abouti à un arbitrage ambigu.
- `ffbb_reliability_conflicts_total` : Nombre total de rencontres détectées avec des statuts contradictoires.
- `ffbb_reliability_unresolved_teams_total` : Nombre d'équipes non résolues.
- `ffbb_reliability_resolution_time_seconds` : Histogramme des temps de résolution stricts.
- `ffbb_reliability_cache_hits_total` / `_misses_total` : Efficacité du cache SWR à deux niveaux.

Les logs applicatifs sont émis au format JSON structuré avec traçabilité (`request_id`, `club_id`, `poule_id`, `match_status`, `resolution_strategy`).

---

## 7. Conformité MCP & Budget Token

- L'ensemble des 25 outils MCP respecte strictement le plafond unitaire de taille de schéma JSON (budget de conformité < 45 000 caractères au total) pour éviter tout dépassement de contexte lors de l'orchestration multi-agents.
- Les réponses utilisent une enveloppe typée `McpResponseEnvelope` incluant statut (`ok`, `ambiguous`, `not_found`, `partial`, `stale`, `invalid_request`), métadonnées de provenance et avertissements contextualisés.
