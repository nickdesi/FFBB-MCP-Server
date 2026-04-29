# Installation

L'instance publique est prête à l'emploi. Voici comment l'intégrer dans vos outils favoris.

## 🔗 Endpoint Canonique
> **`https://ffbb.desimone.fr/mcp`**

## 🤖 Claude Desktop

Ajoutez cette configuration dans votre fichier `claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "ffbb": {
      "httpUrl": "https://ffbb.desimone.fr/mcp"
    }
  }
}
```

## 💻 Cursor / VS Code (Extension MCP)

Dans l'interface de gestion MCP de votre éditeur :

1. **Type** : `Streamable HTTP` (ou `HTTP` selon le client)
2. **URL** : `https://ffbb.desimone.fr/mcp`

## 🛠️ Smithery (Installation auto)

Pour une installation automatisée via Smithery :

```bash
npx -y @smithery/cli@latest install @nickdesi/mcpffbb \
  --client claude \
  --mcp-url https://ffbb.desimone.fr/mcp
```

## 🐳 Déploiement Local (Docker)

Si vous souhaitez héberger votre propre instance :

```bash
docker run -d \
  --name ffbb-mcp \
  -p 8000:8000 \
  nickdesi/ffbb-mcp-server:latest
```
