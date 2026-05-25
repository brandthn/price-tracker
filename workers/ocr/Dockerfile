# syntax=docker/dockerfile:1.7
# Build from monorepo root: docker build -f workers/ocr/Dockerfile .

FROM python:3.11-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

COPY dev_ocr /receipt_ocr_src
COPY workers/ocr/pyproject.toml workers/ocr/README.md ./workers/ocr/
COPY workers/ocr/pricetracker_ocr ./workers/ocr/pricetracker_ocr

WORKDIR /app/workers/ocr
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-cache /receipt_ocr_src


FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/workers/ocr/.venv /app/.venv
COPY --chown=app:app workers/ocr/pricetracker_ocr ./pricetracker_ocr

USER app

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn pricetracker_ocr.main:app --host 0.0.0.0 --port ${PORT}"]
