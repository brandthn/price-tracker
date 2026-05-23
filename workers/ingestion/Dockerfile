# syntax=docker/dockerfile:1.7
# Multi-stage : étape `builder` figée par uv → couche runtime mince.
# uv compile et installe les deps dans un .venv qui est copié tel quel
# dans l'image finale → pas de uv en runtime, pas de cache pip à purger.

FROM python:3.11-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

# uv binary statique — pinné pour reproductibilité.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

# 1) deps seules — couche cachée tant que pyproject/uv.lock ne bougent pas.
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 2) projet — couche invalidée à chaque changement de code.
COPY pricetracker_ingestion ./pricetracker_ingestion
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# Pas de root au runtime.
RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app pricetracker_ingestion ./pricetracker_ingestion

USER app

EXPOSE 8080

# Cloud Run lit $PORT. uvicorn écoute toutes les interfaces.
CMD ["sh", "-c", "exec uvicorn pricetracker_ingestion.main:app --host 0.0.0.0 --port ${PORT}"]
