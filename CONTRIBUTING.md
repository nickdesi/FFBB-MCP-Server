# 🤝 Contribuer au FFBB MCP Server

Merci de l'intérêt que vous portez au projet ! Ce document explique comment configurer votre environnement et soumettre des modifications.

## Règles communautaires

Toute contribution doit respecter le [code de conduite](CODE_OF_CONDUCT.md). Pour les questions d'usage, consultez [SUPPORT.md](SUPPORT.md). Pour les vulnérabilités, suivez [SECURITY.md](SECURITY.md) et n'ouvrez pas d'issue publique.

## 🛠️ Configuration du Développement

Ce projet utilise `uv` pour une gestion ultra-rapide des dépendances.

1. **Cloner le repository** (avec les sous-modules) :

    ```bash
    git clone --recursive https://github.com/nickdesi/FFBB-MCP-Server.git
    cd FFBB-MCP-Server
    ```

2. **Configuration de l'environnement** :

    ```bash
    # Créer et activer l'environnement virtuel
    uv venv
    source .venv/bin/activate  # macOS/Linux
    # .\.venv\Scripts\activate  # Windows

    # Installer en mode éditable avec les outils de dev
    uv sync
    ```

## 📏 Standards de Qualité

Pour maintenir une base de code propre :

- **Linting/Formatting** : Utilisez `ruff` (déjà configuré).

    ```bash
    uv run ruff format .
    uv run ruff check .
    ```

- **Tests** : Lancez les tests avant chaque commit.

    ```bash
    uv run pytest
    ```

### ✅ Checklist avant commit

Avant de pousser vos changements :

- [ ] Code formaté : `uv run ruff format .`
- [ ] Lint OK : `uv run ruff check .`
- [ ] Tests unitaires OK : `uv run pytest`
- [ ] Dépendances synchronisées : `uv.lock` mis à jour et commité (si modifications de dépendances)
- [ ] (Optionnel) Performance critique modifiée : `uv run python tools/measure_services.py`

- **Commits** : Nous suivons les [Conventional Commits](https://www.conventionalcommits.org/).

## 🚀 Soumettre une modification

1. Ouvrez d'abord une issue pour les changements importants ou ambigus.
2. Créez une branche descriptive (`git checkout -b fix/issue-name`).
3. Commitez vos changements de manière atomique avec des [Conventional Commits](https://www.conventionalcommits.org/).
4. Ouvrez une Pull Request avec une description claire du "Pourquoi" et du "Comment".
5. Vérifiez que la CI (GitHub Actions) passe.

### Attentes de revue

- Gardez les PR ciblées : pas de refactor non lié au changement.
- Ajoutez ou mettez à jour les tests si le comportement change.
- Mettez à jour la documentation lorsque l'usage, l'API ou le déploiement change.
- Les mainteneurs peuvent demander des ajustements ou fermer une proposition hors périmètre.

---
*Ensemble, codons le futur du basket français !* 🏀

## Gestion des Dépendances

Nous utilisons `uv` pour gérer les dépendances. Le fichier `uv.lock` garantit la reproductibilité absolue des environnements (notamment en production).

- **Mettre à jour les dépendances** : `uv lock --upgrade`
- **Ajouter une dépendance** : `uv add <package>`
- **Supprimer une dépendance** : `uv remove <package>`

> [!WARNING]
> Après tout `uv add` ou `uv remove`, vous devez **obligatoirement commiter** le fichier `uv.lock` mis à jour avant de pusher. Le build Docker de production utilise `uv sync --frozen` et échouera systématiquement si le fichier `uv.lock` n'est pas synchronisé avec votre `pyproject.toml`.
