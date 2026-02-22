# Utilise l'image officielle python slim
FROM python:3.12-slim

# Environnement optimisé pour l'exécution Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_MODE=http \
    PORT=9123 \
    HOST=0.0.0.0

WORKDIR /app

# Installation de 'uv' pour une installation plus rapide et stricte (optionnel mais fortement recommandé)
COPY --from=ghcr.io/astral-sh/uv:0.4.15 /uv /bin/uv

# Copie d'abord les fichiers de de configuration pour le cache Docker
COPY pyproject.toml .

# Installe les dépendances avec uv
RUN uv pip install --system --no-cache .

# Ensuite, on copie le reste du code source
COPY . /app/

# Expose le port de l'app
EXPOSE 9123

# Lancement de l'app
CMD ["ffbb-mcp"]

