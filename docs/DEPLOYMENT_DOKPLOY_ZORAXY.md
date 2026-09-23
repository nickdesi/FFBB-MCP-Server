# 🐳 Guide de Déploiement (Dokploy & Zoraxy Reverse Proxy)

Ce guide détaille l'exposition sécurisée et performante de **FFBB MCP Server** sur `https://ffbb.desimone.fr/mcp` via **Dokploy PaaS** et le reverse proxy **Zoraxy**.

---

## 1. Déploiement du Conteneur sur Dokploy

Le serveur FFBB MCP est exécuté en tant que conteneur Docker géré par **Dokploy** (`https://dokploy.desimone.fr`, LXC 103) :

- **Type d'application** : Docker / Application Git
- **Dépôt** : `https://github.com/nickdesi/FFBB-MCP-Server`
- **Branche** : `main`
- **Build Type** : `Dockerfile`
- **Port interne conteneur** : `9123`

### Variables d'Environnement recommandées

À renseigner dans la section **Environment** de l'application Dokploy :

| Variable | Valeur recommandée | Rôle |
| :--- | :--- | :--- |
| `MCP_MODE` | `http` | Active le transport MCP moderne **Streamable HTTP** sur `/mcp`. |
| `MCP_STATELESS_HTTP` | `true` | Active le mode Stateless Core (MCP Spec 2026-07-28 sans session). |
| `PORT` | `9123` | Port HTTP d'écoute du serveur FastAPI/Starlette. |
| `PUBLIC_URL` | `https://ffbb.desimone.fr` | URL publique utilisée pour les métadonnées, liens et sitemap. |
| `ALLOWED_HOSTS` | `ffbb.desimone.fr` | Protection DNS rebinding & filtrage d'hôtes TransportSecurity. |
| `ALLOWED_ORIGINS` | `https://ffbb.desimone.fr` | Origines CORS autorisées. |
| `ENABLE_DNS_PROTECTION` | `true` | Active la protection d'hôte côté serveur. |
| `TRUSTED_PROXY_HOSTS` | `192.168.1.119,127.0.0.1` | IP du reverse proxy Zoraxy pour la résolution des vraies IPs clientes. |

---

## 2. Configuration Zoraxy Reverse Proxy

Dans l'interface d'administration de **Zoraxy** (`http://192.168.1.119:8000`) :

### Règle Proxy (Proxy Rule)
- **Root Domain / Subdomain** : `ffbb.desimone.fr`
- **Target IP / Port** : `http://192.168.1.146:9123` (ou port hôte mappé par Dokploy sur le LXC 103)
- **TLS / SSL** : Certificat Let's Encrypt / ACME géré automatiquement par Zoraxy.
- **Pass Host Header** : **Activé** (transmet `Host: ffbb.desimone.fr` indispensable pour `TransportSecuritySettings`).
- **Response Buffering** : **Désactivé** (permet le streaming SSE et chunked transfer sans latence).

---

## 3. Spécificité MCP 2026-07-28 (Stateless Core)

Avec la spécification **2026-07-28** :
- **Plus de session obligatoire** : Chaque requête `POST /mcp` est traitée indépendamment.
- **Tolérance totale aux redémarrages** : Aucun risque d'erreur `Missing session ID` si le conteneur ou Zoraxy recharge ses connexions.
- **En-têtes CORS** : Les en-têtes `Mcp-Method` et `Mcp-Name` sont automatiquement autorisés.

---

## 4. Endpoints & Monitoring

- **Endpoint MCP Public** : `https://ffbb.desimone.fr/mcp`
- **Healthcheck** : `https://ffbb.desimone.fr/health` (HTTP 200, spec 2026-07-28)
- **Dashboard HTML** : `https://ffbb.desimone.fr/dashboard`
- **Métriques Prometheus** : `https://ffbb.desimone.fr/metrics`

### Sécurité des endpoints sensibles
Dans Zoraxy, vous pouvez restreindre l'accès à `/metrics`, `/metrics.json` et `/dashboard` :
- Soit par restriction d'adresses IP privées (`192.168.1.0/24`, `10.0.0.0/8`).
- Soit en activant l'authentification HTTP Basic dans Zoraxy pour ces sous-chemins.
