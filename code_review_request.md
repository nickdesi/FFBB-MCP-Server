J'ai finalisé la majorité des actions d'infrastructure et d'amélioration qualité (Sprint 1, structure et _state.py).
Cependant, la scission de `services.py` s'est heurtée à de multiples références croisées et des problèmes circulaires lors des imports depuis `_shared.py` (notamment avec les tests unitaires patchant directement des dépendances spécifiques).
J'ai donc annulé la scission des services (tout est retourné dans `services.py`) pour garantir que les tests passent tous de manière reproductible (100% de succès) sans introduire d'instabilité, tout en ayant correctement isolé `_state.py` et `app_factory.py` / `http_routes.py` !
Je suis à 66% de couverture de code (seuil de 65% atteint).
Puis-je soumettre ?
