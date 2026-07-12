# syntax=docker/dockerfile:1.7
# Build from monorepo root: docker build -f workers/ocr-paddle/Dockerfile .

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
COPY workers/ocr-paddle/pyproject.toml workers/ocr-paddle/README.md ./workers/ocr-paddle/
COPY workers/ocr-paddle/pricetracker_ocr_paddle ./workers/ocr-paddle/pricetracker_ocr_paddle

WORKDIR /app/workers/ocr-paddle
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# Modèles PaddleOCR (détection + reconnaissance fr) téléchargés une fois au
# BUILD depuis le CDN Paddle, puis copiés dans le HOME du user runtime : aucun
# accès réseau ni latence de téléchargement au cold start Cloud Run.
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
RUN HOME=/opt/paddle-home /app/.venv/bin/python -c \
    "from paddleocr import PaddleOCR; PaddleOCR(lang='fr')"


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
COPY --chown=app:app workers/ocr-paddle/pricetracker_ocr_paddle ./pricetracker_ocr_paddle

USER app

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn pricetracker_ocr_paddle.main:app --host 0.0.0.0 --port ${PORT}"]
