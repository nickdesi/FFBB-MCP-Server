# 🐳 Guide de Configuration (Coolify + Nginx Proxy Manager)

Pour que ton serveur soit accessible sur `https://ffbb.desimone.fr/mcp`, voici les étapes à suivre :

## 1. Paramètres Coolify

- **Source** : Ton dépôt GitHub `FFBB-MCP-Server`.
- **Build Pack** : `Docker`.
- **Domain** : `http://ffbb.desimone.fr`
  > [!IMPORTANT]
  > Utilise impérativement `http://` dans Coolify. Si tu mets `https://`, Coolify va essayer de générer son propre certificat Let's Encrypt, ce qui entrera en conflit avec **Nginx Proxy Manager**.

## 2. Variables d'Environnement (Coolify)

Ajoute ces variables dans l'onglet **Environment Variables** :

| Variable | Valeur recommandée | Rôle |
| --- | --- | --- |
| `MCP_MODE` | `http` | Active le transport MCP moderne **Streamable HTTP** sur `/mcp`. `streamable-http` est aussi accepté. |
| `PORT` | `9123` | Port HTTP écouté par le conteneur. |
| `PUBLIC_URL` | `https://ffbb.desimone.fr` | URL publique utilisée pour les métadonnées, liens et vérifications côté serveur. |
| `ALLOWED_HOSTS` | `ffbb.desimone.fr` | Liste des hôtes autorisés en production. |
| `ALLOWED_ORIGINS` | `https://ffbb.desimone.fr` | Origines CORS autorisées. |
| `ENABLE_DNS_PROTECTION` | `true` | Active les protections DNS/host lorsque l'app est exposée publiquement. |

> [!NOTE]
> La valeur historique `MCP_MODE=sse` reste mappée côté serveur vers Streamable HTTP pour compatibilité, mais elle n'est plus recommandée pour une nouvelle installation.

## 3. Configuration Nginx Proxy Manager (NPM)

Puisque tu utilises **Nginx Proxy Manager** pour gérer le trafic :

- **Domain Names** : `ffbb.desimone.fr`
- **Scheme** : `http`
- **Forward Host** : L'adresse IP ou le nom de service Docker de ton container.
- **Forward Port** : `9123`
- **Websockets Support** : facultatif pour l'usage normal. Streamable HTTP fonctionne sur HTTP(S) standard ; active-le seulement si ton proxy l'exige pour d'autres usages.
- **Block Common Exploits** : Tu peux le laisser, mais si tu as une erreur 403, essaie de le désactiver.

## 4. Chemin /mcp

Pas besoin de configurer de path particulier dans NPM ou Coolify. Le code Python du serveur est déjà configuré pour écouter sur `/mcp`.

Ton endpoint final sera :
👉 **`https://ffbb.desimone.fr/mcp`**

## 5. Healthchecks (Monitoring)

Tu peux maintenant utiliser l'endpoint de vérification d'état pour monitorer le service dans Coolify :

- **Path** : `/health`
- **Expected Status Code** : `200`
- L'endpoint retourne un JSON avec `status`, `service`, `version`, `transport`, `uptime_seconds` et des statistiques de cache. Vérifie surtout que `status` vaut `"ok"`.

Tu peux aussi consulter :

- `/metrics` pour Prometheus.
- `/metrics.json` pour un snapshot JSON de supervision.
- `/dashboard` pour le tableau de bord HTML.
