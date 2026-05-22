# Politique de sécurité

## Versions supportées

La branche `main` et la dernière version publiée sont supportées pour les correctifs de sécurité.

## Signaler une vulnérabilité

Ne publiez pas de vulnérabilité dans une issue ou une pull request publique.

Méthode recommandée : utilisez **GitHub Security Advisories / Private vulnerability reporting** si disponible sur le dépôt.

À défaut, contactez le mainteneur via les coordonnées indiquées sur son profil GitHub en incluant :

- une description claire du problème ;
- les versions ou commits concernés ;
- les étapes minimales de reproduction ;
- l'impact potentiel ;
- toute mitigation connue.

## Délais indicatifs

- Accusé de réception : sous 7 jours lorsque possible.
- Triage initial : sous 14 jours lorsque possible.
- Correctif et divulgation : selon la sévérité, la complexité et les dépendances amont.

## Périmètre

Sont principalement dans le périmètre :

- exécution de code non attendue ;
- fuite de secrets ou de données sensibles ;
- vulnérabilités liées au serveur HTTP/MCP ;
- contournement de limites de sécurité documentées ;
- dépendances vulnérables impactant l'exécution du serveur.

Hors périmètre sauf impact démontré :

- indisponibilité ou erreurs provenant directement de l'API FFBB amont ;
- scraping agressif ou abus des services tiers ;
- problèmes nécessitant déjà un accès administrateur à l'hôte ;
- divulgation publique sans coordination préalable.

## Processus de réponse

1. Confirmer la réception du rapport.
2. Reproduire et qualifier la sévérité.
3. Préparer un correctif privé si nécessaire.
4. Publier une version corrigée.
5. Documenter l'impact et les éventuelles actions utilisateur.

## Bonnes pratiques contributeurs

- N'incluez jamais de tokens, cookies, clés API ou données personnelles dans les tests, logs ou issues.
- Utilisez des exemples anonymisés.
- Lancez les contrôles de qualité documentés dans `CONTRIBUTING.md` avant de proposer un correctif.
