#!/usr/bin/env bash
# ==============================================================================
# FFBB MCP Server — Lanceur 1-Clic macOS (.command)
# Double-cliquez sur ce fichier pour installer instantanément le serveur MCP FFBB
# ==============================================================================
clear
echo "🏀 Lancement de l'installateur FFBB MCP pour macOS..."
curl -fsSL https://ffbb.desimone.fr/install.sh | bash

echo ""
read -p "Appuyez sur [Entrée] pour fermer cette fenêtre..."
