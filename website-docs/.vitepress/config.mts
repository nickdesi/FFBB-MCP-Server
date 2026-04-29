import { defineConfig } from 'vitepress'

export default defineConfig({
  title: "FFBB MCP Server",
  description: "Documentation officielle du serveur MCP pour la FFBB",
  base: '/docs/',
  outDir: '../website/docs',
  themeConfig: {
    logo: '/logo.webp',
    nav: [
      { text: 'Accueil', link: '/' },
      { text: 'Guide', link: '/guide/installation' },
      { text: 'Référence', link: '/reference/tools' }
    ],
    sidebar: [
      {
        text: 'Introduction',
        items: [
          { text: 'Pourquoi FFBB MCP ?', link: '/guide/introduction' },
          { text: 'Installation', link: '/guide/installation' },
          { text: 'Exemples d\'utilisation', link: '/guide/examples' }
        ]
      },
      {
        text: 'Référence Technique',
        items: [
          { text: 'Outils disponibles', link: '/reference/tools' },
          { text: 'Architecture', link: '/reference/architecture' },
          { text: 'Performance & Cache', link: '/reference/performance' },
          { text: 'Règles FFBB', link: '/reference/rules' }
        ]
      },
      {
        text: 'Déploiement',
        items: [
          { text: 'Coolify', link: '/deploy/coolify' }
        ]
      }
    ],
    socialLinks: [
      { icon: 'github', link: 'https://github.com/nickdesi/FFBB-MCP-Server' }
    ],
    footer: {
      message: 'Libéré sous licence MIT.',
      copyright: 'Copyright © 2024-présent Nicolas'
    },
    search: {
      provider: 'local'
    }
  },
  head: [
    ['link', { rel: 'icon', href: '/logo.webp' }]
  ],
  appearance: 'dark'
})
