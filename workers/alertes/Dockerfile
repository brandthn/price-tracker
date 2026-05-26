# syntax=docker/dockerfile:1.7
# Multi-stage uv → runtime mince. Identique aux Dockerfiles workers/{off,indices,ingestion}.

FROM python:3.11-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# README.md nécessaire au build : pyproject.toml déclare `readme = "README.md"`,
# hatchling lit le fichier pour assembler la wheel locale (étape `uv sync` ci-dessous).
COPY README.md ./
COPY pricetracker_alertes ./pricetracker_alertes
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app pricetracker_alertes ./pricetracker_alertes

USER app

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn pricetracker_alertes.main:app --host 0.0.0.0 --port ${PORT}"]
