# syntax=docker/dockerfile:1.7
# Build from monorepo root: docker build -f workers/ocr-ppocrv4/Dockerfile .

FROM python:3.11-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Bibliothèques natives requises par paddlepaddle / opencv à l'IMPORT
# (nécessaires ici pour le warm-up des modèles ci-dessous).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY libs/pricetracker_matching /app/libs/pricetracker_matching
COPY libs/pricetracker_receipt_pipeline /app/libs/pricetracker_receipt_pipeline
COPY workers/ocr-ppocrv4/pyproject.toml workers/ocr-ppocrv4/README.md ./workers/ocr-ppocrv4/
COPY workers/ocr-ppocrv4/pricetracker_ocr_ppocrv4 ./workers/ocr-ppocrv4/pricetracker_ocr_ppocrv4

WORKDIR /app/workers/ocr-ppocrv4
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# Modèles PP-OCRv4 mobile (+ fallback paddle_dynamic) téléchargés une fois au
# BUILD depuis le CDN Paddle, puis copiés dans le HOME du user runtime : aucun
# accès réseau ni latence de téléchargement au cold start Cloud Run.
# On instancie le backend réel : il warm-up le profil qui marche ET son fallback.
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
RUN HOME=/opt/paddle-home /app/.venv/bin/python -c \
    "from pricetracker_ocr_ppocrv4.ppocr_v4_backend import PpOcrV4MobileBackend; PpOcrV4MobileBackend(lang='fr')"


FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /opt/paddle-home/ /home/app/
COPY --chown=app:app workers/ocr-ppocrv4/pricetracker_ocr_ppocrv4 ./pricetracker_ocr_ppocrv4

USER app

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn pricetracker_ocr_ppocrv4.main:app --host 0.0.0.0 --port ${PORT}"]
