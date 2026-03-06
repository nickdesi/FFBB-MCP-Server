# 🐳 Guide de Configuration (Coolify + Nginx Proxy Manager)

Pour que ton serveur soit accessible sur `https://ffbb.desimone.fr/mcp`, voici les étapes à suivre :

## 1. Paramètres Coolify

- **Source** : Ton dépôt GitHub `FFBB-MCP-Server`.
- **Build Pack** : `Docker`.

## 2. Variables d'Environnement (Coolify)

Ajoute ces deux variables dans l'onglet **Environment Variables** :

- `MCP_MODE` = `sse`
- `PORT` = `9123`

## 3. Configuration Nginx Proxy Manager (NPM)

Puisque tu utilises **Nginx Proxy Manager** pour gérer le trafic :

- **Domain Names** : `ffbb.desimone.fr`
- **Scheme** : `http`
- **Forward Host** : L'adresse IP ou le nom de service Docker de ton container.
- **Forward Port** : `9123`
- **Websockets Support** : **ACTIVÉ** (Crucial pour le flux streamable MCP).
- **Block Common Exploits** : Tu peux le laisser, mais si tu as une erreur 403, essaie de le désactiver.

## 4. Chemin /mcp

Pas besoin de configurer de path particulier dans NPM ou Coolify. Le code Python du serveur est déjà configuré pour écouter sur `/mcp`.

Ton endpoint final sera :
👉 **`https://ffbb.desimone.fr/mcp`**
