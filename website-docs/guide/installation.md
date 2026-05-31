# Installation

L'instance publique est prête à l'emploi. Voici comment l'intégrer dans vos outils favoris.

## 🔗 Endpoint Canonique
> **`https://ffbb.desimone.fr/mcp`**

## 🤖 Claude Desktop

Il existe deux manières d'ajouter le serveur MCP FFBB à Claude :

### Option A : Via l'interface de Claude (Recommandé)
Si votre version de Claude dispose de l'écran des connecteurs :
1. Allez dans les **Paramètres** de Claude puis dans **Connecteurs** (ou **Plugins**).
2. Cliquez sur **Ajouter un connecteur personnalisé**.
3. Renseignez l'URL publique : `https://ffbb.desimone.fr/mcp` et validez.

### Option B : Via `claude_desktop_config.json`
Pour une intégration par fichier de configuration, vous devez utiliser le bridge SSE officiel via `npx` car Claude Desktop requiert un transport `stdio` local :

```json
{
  "mcpServers": {
    "ffbb": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/client-sse",
        "https://ffbb.desimone.fr/mcp"
      ]
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
