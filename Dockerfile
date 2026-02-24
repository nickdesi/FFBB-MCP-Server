# Utilise l'image officielle python slim
FROM python:3.12-slim

# Environnement optimisé pour l'exécution Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_MODE=http \
    PORT=9123 \
    HOST=0.0.0.0

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Installation de 'uv'
COPY --from=ghcr.io/astral-sh/uv:0.4.15 /uv /bin/uv

# Settings for uv to work properly in Docker
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Copie des fichiers de config pour le cache
COPY pyproject.toml uv.lock ./

# Installe les dépendances sans le projet lui-même
RUN uv sync --frozen --no-dev --no-install-project

# Copie du reste du code source
COPY . .

# Installe le projet
RUN uv sync --frozen --no-dev

# Expose le port
EXPOSE 9123

# Lancement
CMD ["ffbb-mcp"]
