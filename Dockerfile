FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Configurer l'environnement MCP en mode Serveur Web (SSE)
ENV MCP_MODE=sse
ENV PORT=9123
ENV HOST=0.0.0.0

WORKDIR /app

# Installer Git (nécessaire pour installer la dépendance git referenced in pyproject)
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Copier sources
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY assets/ ./assets/

# Mettre à jour pip puis installer le package et ses dépendances
RUN python -m pip install --upgrade pip setuptools wheel && \
	python -m pip install --no-cache-dir -e .

# Exposer le port configuré
EXPOSE 9123

# Commande de lancement (utilise l'entry-point défini dans pyproject.toml)
CMD ["ffbb-mcp"]
