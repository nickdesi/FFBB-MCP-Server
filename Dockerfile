FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Configurer l'environnement MCP en mode Serveur Web (SSE)
ENV MCP_MODE=sse
ENV PORT=9123
ENV HOST=0.0.0.0

WORKDIR /app

# Installation de Git (requis car ffbb-api-client-v3 est tapé via url locale/git)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Installer UV, rapide et léger
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY src/ ./src/

# Lier et l'installer
RUN uv pip install --system -e .

EXPOSE 9123

# Lancement
CMD ["ffbb-mcp"]
