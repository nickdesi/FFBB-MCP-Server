# Contribuer au Serveur MCP FFBB

Merci de vouloir contribuer ! Voici comment nous aider :

## Signaler un bug

Ouvrez une [Issue](https://github.com/nickdesi/FFBB-MCP-Server/issues) en décrivant le problème et comment le reproduire.

## Proposer une amélioration

1. Forkez le projet.
2. Créez une branche (`git checkout -b feature/ma-super-feature`).
3. Commitez vos changements (`git commit -m 'feat: ajout de ma super feature'`).
4. Poussez vers votre fork (`git push origin feature/ma-super-feature`).
5. Ouvrez une Pull Request.

## Développement local

```bash
# Installation
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Tests
pytest tests/ -v
```

## Standards

- Utilisez [Black](https://github.com/psf/black) pour le formatage du code.
- Écrivez des tests pour chaque nouvelle fonctionnalité.
- Respectez les conventions de commit [Conventional Commits](https://www.conventionalcommits.org/).
