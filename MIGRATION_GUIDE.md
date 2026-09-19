# GUIDE DE MIGRATION — FIABILISATION V1.15.0+
## Serveur FFBB MCP (Model Context Protocol)

Ce guide détaille les changements apportés dans la version **1.15.0** du serveur FFBB MCP. Cette mise à jour majeure renforce la fiabilité, la déterminisme et l'intégrité des données sportives et réglementaires exposées aux agents IA et aux applications clientes.

---

## 1. Synthèse des Évolutions Majeures

| Domaine | Comportement Antérieur (< 1.15.0) | Nouveau Comportement (>= 1.15.0) |
| :--- | :--- | :--- |
| **Résolution d'Équipe** | Fallback permissif potentiel sur d'autres niveaux ou catégories | **Résolution stricte** : rejet immédiat des confusions (NM3 != PNM), retour `ambiguous` explicite |
| **Calendrier Club** | Élargissement silencieux aux matchs de tout le club | **Calendrier scoped** (`scope=team|club|competition`), exclusion des amicaux et coupes par défaut |
| **Statut des Matchs** | Statuts textuels hétérogènes (`JOUÉ`, `À venir`, etc.) | **Enum canonique** (`CanonicalMatchStatus`), détection des conflits (`unknown_conflict`) |
| **Agrégats & Bilans** | Risque d'inclure des matchs annulés ou en anomalie de score | **Sas d'éligibilité strict** (`is_match_eligible_for_aggregate`), 0 match en conflit comptabilisé |
| **Règlements** | Recherche textuelle brute sans contexte de primauté | **Hiérarchie des normes** (Fédéral > Régional > Départemental) + empreinte SHA-256 + disclaimer légal |
| **Schémas MCP** | Risque de saturation de contexte pour les LLM | **Budget token strict** (< 45 000 caractères cumulés pour les 25 outils) |

---

## 2. Évolution des Réponses & Gestion de l'Ambiguïté

### 2.1. Outil `ffbb_resolve_team`

Auparavant, si une catégorie était incomplète ou si plusieurs équipes concourraient dans des championnats différents, le serveur pouvait arbitrairement retourner la première équipe trouvée.

Désormais, en cas d'équivoque, le statut devient `"ambiguous"` :

#### Exemple de Réponse Ambiguë :
```json
{
  "status": "ambiguous",
  "team": null,
  "candidates": [
    {
      "team_id": "200000003057825",
      "team_label": "Clermont Basket - 1",
      "competition": "Pré-Nationale Masculine",
      "competition_type": "CHAMPIONNAT",
      "numero_equipe": "1"
    },
    {
      "team_id": "200000003057826",
      "team_label": "Clermont Basket - 2",
      "competition": "Régionale 2 Masculine",
      "competition_type": "CHAMPIONNAT",
      "numero_equipe": "2"
    }
  ],
  "ambiguity": "Plusieurs engagements (2) correspondent à cette recherche.",
  "clarification_prompt": "L'équipe Clermont Basket a 2 engagements distincts... Précisez `competition_id`, `competition_type` ou `numero_equipe`."
}
```

#### Recommandation pour les Agents IA :
Lorsque `status == "ambiguous"`, utilisez `clarification_prompt` pour interroger l'utilisateur ou relancez la requête avec le paramètre `numero_equipe` ou `engagement_id` fourni dans `candidates`.

---

## 3. Nouveaux Paramètres de Scoping dans `get_calendrier_club`

L'outil de calendrier propose désormais un filtrage strict pour cibler exactement le besoin :

```python
# Exemple d'appel Python
result = await get_calendrier_club_service(
    club_name="Clermont Basket",
    categorie="NM3",
    scope="team",  # 'team' | 'club' | 'competition'
    include_friendlies=False,  # Exclut PLAT, AMIC (défaut: False)
    include_reserves=False,  # Exclut équipes 2, 3... si équipe fanion visée
    status_filter=["scheduled"],  # Filtre par statut canonique
    strict_filters=True,  # Interdit l'élargissement silencieux
)
```

### Comportement si aucune rencontre ne correspond :
Si l'équipe ciblée n'a aucun match programmé dans le scope demandé, le serveur retourne :
```json
{
  "status": "not_found",
  "items": [],
  "warning": "Aucun engagement ne correspond aux critères spécifiés (catégorie='NM3', scope='team'). Aucun élargissement silencieux au calendrier global du club n'est autorisé."
}
```
L'agent IA est ainsi garanti de ne jamais confondre le calendrier d'une équipe senior avec celui des équipes jeunes du même club.

---

## 4. Machine à États Canonique des Rencontres

Chaque objet match dans les réponses MCP contient désormais les champs canoniques normalisés :

```json
{
  "id": "123456",
  "date": "2026-10-14T20:00:00+02:00",
  "statut": "final",
  "canonical_status": "final",
  "data_quality": {
    "level": "verified",
    "is_reliable": true,
    "issues": []
  },
  "score_equipe1": 78,
  "score_equipe2": 72
}
```

Si une anomalie survient dans les données brutes (ex: score affiché mais statut "non commencé") :
- `canonical_status` = `"unknown_conflict"`
- `data_quality.level` = `"conflict"`
- `data_quality.issues` = `["Statut déclaré non commencé mais score strictement positif (78-72)"]`
- Le match est automatiquement **écarté du calcul des bilans officiels**.

---

## 5. Moteur Réglementaire & Hiérarchie des Normes

Les outils `ffbb_search_regulations` et `ffbb_get_regulation_article` retournent désormais des métadonnées de sécurité juridique :

```json
{
  "document_id": "règlements_généraux_ffbb",
  "article_number": "51",
  "titre": "Règles relatives au brûlage des joueurs",
  "applicability": {
    "level": "federal",
    "priority_rank": 1,
    "disclaimer": "Information réglementaire indicative issue des documents indexés...",
    "content_hash": "a1b2c3d4e5f6..."
  }
}
```

---

## 6. Checklist de Validation pour les Développeurs

- [x] Vérifier que votre client gère le statut `ambiguous` lors des résolutions d'équipe.
- [x] Remplacer les filtres manuels d'amicaux par le paramètre natif `include_friendlies=False`.
- [x] Utiliser `canonical_status` plutôt que des comparaisons de chaînes brutes sur `statut`.
- [x] Afficher l'avertissement réglementaire `disclaimer` en cas de consultation des règles officielles.
