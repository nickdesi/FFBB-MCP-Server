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

### Configuration Avancée pour le Streaming MCP (SSE)

Dans l'onglet **Custom Nginx Configuration** (Advanced) de ton proxy host dans NPM, ajoute ces directives pour éviter la mise en cache des flux SSE et empêcher les déconnexions intempestives :

```nginx
# Désactiver le buffering pour le streaming SSE (requis pour MCP)
proxy_buffering off;
proxy_cache off;

# Timeouts adaptés au streaming MCP
proxy_read_timeout 300s;
proxy_send_timeout 300s;
proxy_connect_timeout 60s;
```


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

## 6. Sécurité des endpoints opérationnels

Plusieurs endpoints exposent des données de supervision ou des actions administrateur. Il est **fortement recommandé** de les protéger au niveau du reverse proxy (Nginx Proxy Manager, Traefik, etc.) :

| Endpoint | Méthode | Risque | Protection recommandée |
|----------|---------|--------|------------------------|
| `/metrics` | GET | Exposition de métriques Prometheus (cache, latences) | IP whitelist ou basic auth NPM |
| `/metrics.json` | GET | Snapshot JSON de santé (version, transport, stats cache) | IP whitelist ou basic auth NPM |
| `/dashboard` | GET | Dashboard HTML avec stats runtime | IP whitelist ou basic auth NPM |
| `/benchmark` | GET | Page d'information benchmark | Pas critique, mais restreindre en production |
| `/benchmark/run` | POST | Déclenche un run de benchmark (désactivé par défaut via `FFBB_ENABLE_BENCHMARK`) | Laisser désactivé en production |
| `/cache/warmup` | POST/GET | Pré-chauffe ou lit l'état du cache | IP whitelist (usage CI/admin uniquement) |

### Configuration recommandée Nginx Proxy Manager

Dans l'onglet **Advanced** de ton proxy host NPM, ajouter :

```nginx
# Protéger les endpoints de supervision
location /metrics {
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    allow 192.168.0.0/16;
    deny all;
    proxy_pass http://<container>:9123;
}

location /metrics.json {
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    allow 192.168.0.0/16;
    deny all;
    proxy_pass http://<container>:9123;
}

location /dashboard {
    auth_basic "Admin Area";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://<container>:9123;
}

location /cache/warmup {
    allow 127.0.0.1;
    deny all;
    proxy_pass http://<container>:9123;
}
```

### Variables d'environnement de sécurité

| Variable | Rôle |
|----------|------|
| `ALLOWED_HOSTS` | Restreint les hosts acceptés (anti DNS rebinding). En production : `ffbb.desimone.fr` |
| `ALLOWED_ORIGINS` | Restreint les origines CORS. En production : `https://ffbb.desimone.fr` |
| `TRUSTED_PROXY_HOSTS` | IP des proxies de confiance (ex: NPM). Défaut : `127.0.0.1` |
| `FFBB_ENABLE_BENCHMARK` | Active l'endpoint `/benchmark/run`. Laisser vide en production. |
| `FFBB_WARMUP_API_KEY` | Si définie, `POST /cache/warmup` exige `Authorization: Bearer <clé>` (rejet `401` sinon). Recommandée en production même derrière NPM. |
| `FFBB_WARMUP_MAX_ORGANISMES` | Borne max d'organismes par préchauffage (défaut 50, rejet `413` au-delà). |
