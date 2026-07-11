# syntax=docker/dockerfile:1.7
# Build from monorepo root: docker build -f workers/ocr-vlm-groq/Dockerfile .

FROM python:3.11-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

COPY libs/pricetracker_matching /app/libs/pricetracker_matching
COPY libs/pricetracker_receipt_pipeline /app/libs/pricetracker_receipt_pipeline
COPY workers/ocr-vlm-groq/pyproject.toml workers/ocr-vlm-groq/README.md ./workers/ocr-vlm-groq/
COPY workers/ocr-vlm-groq/pricetracker_ocr_vlm_groq ./workers/ocr-vlm-groq/pricetracker_ocr_vlm_groq

WORKDIR /app/workers/ocr-vlm-groq
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
COPY --chown=app:app workers/ocr-vlm-groq/pricetracker_ocr_vlm_groq ./pricetracker_ocr_vlm_groq

USER app

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn pricetracker_ocr_vlm_groq.main:app --host 0.0.0.0 --port ${PORT}"]
