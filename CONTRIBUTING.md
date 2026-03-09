# 🤝 Contribuer au FFBB MCP Server

Merci de l'intérêt que vous portez au projet ! Ce document explique comment configurer votre environnement et soumettre des modifications.

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
    uv pip install -e ".[dev]"
    ```

## 📏 Standards de Qualité

Pour maintenir une base de code propre :

- **Linting/Formatting** : Utilisez `ruff` (déjà configuré).

    ```bash
    ruff format .
    ruff check .
    ```

- **Tests** : Lancez les tests avant chaque commit.

    ```bash
    pytest tests/
    ```

- **Commits** : Nous suivons les [Conventional Commits](https://www.conventionalcommits.org/).

## 🚀 Soumettre une modification

1. Créez une branche descriptive (`git checkout -b fix/issue-name`).
2. Commitez vos changements de manière atomique.
3. Vérifiez que la CI (GitHub Actions) passe.
4. Ouvrez une Pull Request avec une description claire du "Pourquoi" et du "Comment".

---
*Ensemble, codons le futur du basket français !* 🏀
