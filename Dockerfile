# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Installer Git
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Copier sources
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY assets/ ./assets/
COPY website/ ./website/

# Créer venv et installer
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir .

# Stage 2: Runtime
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MCP_MODE=sse
ENV PORT=9123
ENV HOST=0.0.0.0
ENV PATH="/opt/venv/bin:$PATH"

# Créer un utilisateur non-root
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copier venv
COPY --from=builder /opt/venv /opt/venv

# Copier les statiques (utilisés par le code)
COPY assets/ ./assets/
COPY website/ ./website/

RUN chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request, sys; sys.exit(0) if urllib.request.urlopen('http://localhost:9123/health').getcode() == 200 else sys.exit(1)"

EXPOSE 9123

CMD ["ffbb-mcp"]
