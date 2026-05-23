FROM python:3.14-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /build

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY assets/ ./assets/
COPY website/ ./website/

RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MCP_MODE=streamable-http
ENV PORT=9123
ENV HOST=0.0.0.0
ENV PATH="/opt/venv/bin:$PATH"

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
ENV HOME=/app

COPY --from=builder /opt/venv /opt/venv
COPY assets/ ./assets/
COPY website/ ./website/

RUN chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0) if urllib.request.urlopen('http://localhost:9123/health').getcode() == 200 else sys.exit(1)"

EXPOSE 9123

CMD ["ffbb-mcp"]
