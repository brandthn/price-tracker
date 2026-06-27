# syntax=docker/dockerfile:1.7
# Build from monorepo root: docker build -f workers/ocr-llm/Dockerfile .

FROM python:3.11-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

COPY dev_ocr /app/dev_ocr
COPY workers/ocr-llm/pyproject.toml workers/ocr-llm/README.md ./workers/ocr-llm/
COPY workers/ocr-llm/pricetracker_ocr_llm ./workers/ocr-llm/pricetracker_ocr_llm

WORKDIR /app/workers/ocr-llm
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev


FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app workers/ocr-llm/pricetracker_ocr_llm ./pricetracker_ocr_llm

USER app

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn pricetracker_ocr_llm.main:app --host 0.0.0.0 --port ${PORT}"]
