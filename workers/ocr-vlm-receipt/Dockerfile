# syntax=docker/dockerfile:1.7
# Build from monorepo root: docker build -f workers/ocr-vlm-receipt/Dockerfile .

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
COPY workers/ocr-vlm-receipt/pyproject.toml workers/ocr-vlm-receipt/README.md ./workers/ocr-vlm-receipt/
COPY workers/ocr-vlm-receipt/pricetracker_ocr_vlm_receipt ./workers/ocr-vlm-receipt/pricetracker_ocr_vlm_receipt

WORKDIR /app/workers/ocr-vlm-receipt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# Backbones HF (CLIP ViT-B/16 + SmolLM2-360M) mis en cache au BUILD :
# `ReceiptVLM.from_merged_checkpoint` appelle `from_pretrained` au chargement,
# or Cloud Run n'a pas d'egress internet public (PRIVATE_RANGES_ONLY).
ENV HF_HOME=/opt/hf-cache
RUN /app/.venv/bin/python -c "\
from transformers import AutoModelForCausalLM, AutoTokenizer, CLIPVisionModel; \
CLIPVisionModel.from_pretrained('openai/clip-vit-base-patch16'); \
AutoTokenizer.from_pretrained('HuggingFaceTB/SmolLM2-360M-Instruct'); \
AutoModelForCausalLM.from_pretrained('HuggingFaceTB/SmolLM2-360M-Instruct')"


FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf-cache \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PORT=8080

# libgomp1 : runtime OpenMP requis par torch.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /opt/hf-cache /opt/hf-cache
COPY --chown=app:app workers/ocr-vlm-receipt/pricetracker_ocr_vlm_receipt ./pricetracker_ocr_vlm_receipt

USER app

EXPOSE 8080

# Le checkpoint .pt n'est PAS dans l'image : téléchargé depuis PRT_MODEL_GCS_URI
# au démarrage (lifespan) vers PRT_MODEL_LOCAL_DIR.
CMD ["sh", "-c", "exec uvicorn pricetracker_ocr_vlm_receipt.main:app --host 0.0.0.0 --port ${PORT}"]
