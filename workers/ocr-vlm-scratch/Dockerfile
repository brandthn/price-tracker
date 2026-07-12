# syntax=docker/dockerfile:1.7
# Build from monorepo root: docker build -f workers/ocr-vlm-scratch/Dockerfile .

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
# COPY SÉLECTIF de dev_ocr/vlm_training : `checkpoints/` pèse ~3,7 Go et n'a
# rien à faire dans l'image (les poids viennent de GCS au démarrage).
COPY dev_ocr/vlm_training/pyproject.toml dev_ocr/vlm_training/README.md /app/dev_ocr/vlm_training/
COPY dev_ocr/vlm_training/receipt_vlm /app/dev_ocr/vlm_training/receipt_vlm
COPY workers/ocr-vlm-scratch/pyproject.toml workers/ocr-vlm-scratch/README.md ./workers/ocr-vlm-scratch/
COPY workers/ocr-vlm-scratch/pricetracker_ocr_vlm_scratch ./workers/ocr-vlm-scratch/pricetracker_ocr_vlm_scratch

WORKDIR /app/workers/ocr-vlm-scratch
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev


FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# libgomp1 : runtime OpenMP requis par torch.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app workers/ocr-vlm-scratch/pricetracker_ocr_vlm_scratch ./pricetracker_ocr_vlm_scratch

USER app

EXPOSE 8080

# Checkpoint .pt + tokenizer .json hors image : téléchargés depuis
# PRT_MODEL_GCS_URI / PRT_TOKENIZER_GCS_URI au démarrage (lifespan).
CMD ["sh", "-c", "exec uvicorn pricetracker_ocr_vlm_scratch.main:app --host 0.0.0.0 --port ${PORT}"]
