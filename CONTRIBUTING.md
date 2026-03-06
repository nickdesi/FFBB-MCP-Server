# 🤝 Contribuer au FFBB MCP Server

Merci de l'intérêt que vous portez au projet ! Ce document explique comment configurer votre environnement et soumettre des modifications.

## 🛠️ Configuration du Développement

Ce projet utilise `uv` pour la gestion des dépendances.

1. **Cloner le repository** (avec les sous-modules) :

    ```bash
    git clone --recursive https://github.com/nickdesi/FFBB-MCP-Server.git
    cd FFBB-MCP-Server
    ```

2. **Installer les dépendances** :

    ```bash
    uv venv
    source .venv/bin/activate  # Sur macOS/Linux
    uv pip install -e ".[dev]"
    ```

3. **Gérer le client API (Submodule)** :
    Le client `FFBBApiClientV3_Ref` est une dépendance interne. Si vous modifiez ce dossier, n'oubliez pas de commiter à l'intérieur du dossier :

    ```bash
    cd FFBBApiClientV3_Ref
    git add . && git commit -m "..."
    cd ..
    git add FFBBApiClientV3_Ref
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
