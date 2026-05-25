"""Constants shared across the package.

Centralising the field names of the output schema avoids magic strings
in the parser and makes refactors straightforward.
"""

from __future__ import annotations

from enum import Enum


class TicketField(str, Enum):
    """Top-level keys of the output JSON schema."""

    TICKET = "ticket"
    DATE = "date"
    CHAINE = "chaine_supermarche"
    ADRESSE = "adresse"
    PRODUITS = "produits"


class ProductField(str, Enum):
    """Keys of a single product entry."""

    NOM = "nom_produit"
    PRIX = "prix_unitaire_ou_kg"
    UNITES = "unites"


OUTPUT_DATE_FORMAT = "%Y%m%d %H:%M"
"""Target date format: ``yyyyMMdd HH:mm``."""


class BackendName(str, Enum):
    """Identifiers accepted by the backend factory / env variable."""

    PADDLE = "paddle"
    PPOCRV4 = "ppocrv4"
    TESSERACT = "tesseract"
    EASYOCR = "easyocr"
    VLM = "vlm"


ENV_BACKEND = "RECEIPT_OCR_BACKEND"
"""Name of the environment variable selecting the default backend."""

ENV_MAX_IMAGE_SIDE = "RECEIPT_OCR_MAX_IMAGE_SIDE"
"""Max longest image side (px) before OCR. Set ``0`` to disable resizing."""

ENV_CPU_THREADS = "RECEIPT_OCR_CPU_THREADS"
"""Max CPU threads for Paddle/BLAS (default ``2``). Lower = less system freeze."""

DEFAULT_MAX_IMAGE_SIDE = 1280
DEFAULT_CPU_THREADS = 2

# PP-OCRv4 mobile backend — smaller input for speed (mobile CPU target).
DEFAULT_PPOCRV4_MAX_IMAGE_SIDE = 640
ENV_PPOCRV4_MAX_IMAGE_SIDE = "RECEIPT_OCR_PPOCRV4_MAX_IMAGE_SIDE"

# Lighter PaddleOCR 3.x models (much faster than the server variants).
PADDLE_MOBILE_DET_MODEL = "PP-OCRv4_mobile_det"

# VLM backend — model selection inside BackendName.VLM
class VlmModelName(str, Enum):
    """Registry ids for :func:`receipt_ocr.backends.vlm.build_vlm_provider`."""

    MOONDREAM_0_5B = "moondream-0.5b"
    GROQ_LLAMA4_SCOUT = "groq-llama4-scout"


ENV_VLM_MODEL = "RECEIPT_VLM_MODEL"
ENV_VLM_MODEL_PATH = "RECEIPT_VLM_MODEL_PATH"
ENV_VLM_MAX_IMAGE_SIDE = "RECEIPT_VLM_MAX_IMAGE_SIDE"
ENV_VLM_MODE = "RECEIPT_VLM_MODE"
ENV_VLM_MAX_RETRIES = "RECEIPT_VLM_MAX_RETRIES"
ENV_VLM_CROP = "RECEIPT_VLM_CROP"
ENV_VLM_CROP_MARGIN = "RECEIPT_VLM_CROP_MARGIN"
ENV_VLM_JPEG_QUALITY = "RECEIPT_VLM_JPEG_QUALITY"
ENV_VLM_TEMPERATURE = "RECEIPT_VLM_TEMPERATURE"
ENV_VLM_MAX_TOKENS = "RECEIPT_VLM_MAX_TOKENS"

DEFAULT_VLM_MODEL = VlmModelName.MOONDREAM_0_5B.value

# Groq cloud VLM provider
ENV_GROQ_API_KEY = "GROQ_API_KEY"
ENV_GROQ_API_KEY_LEGACY = "groq_key"
ENV_GROQ_MODEL = "RECEIPT_GROQ_MODEL"
DEFAULT_GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_BASE64_MAX_BYTES = 3_500_000
DEFAULT_VLM_MAX_IMAGE_SIDE = 1536
DEFAULT_VLM_MAX_RETRIES = 2
DEFAULT_VLM_CROP_MARGIN = 0.05
DEFAULT_VLM_JPEG_QUALITY = 95
DEFAULT_VLM_TEMPERATURE = 0.1
DEFAULT_VLM_MAX_TOKENS = 1024
DEFAULT_GROQ_MAX_TOKENS = 4096


class VlmMode(str, Enum):
    """How :class:`VlmBackend` asks Moondream to read a receipt."""

    TRANSCRIBE = "transcribe"
    JSON = "json"
    MULTIPASS = "multipass"


class VlmCropMode(str, Enum):
    """Receipt region cropping before VLM inference."""

    AUTO = "auto"
    CENTER = "center"
    OFF = "off"


DEFAULT_VLM_MODE = VlmMode.TRANSCRIBE.value

MOONDREAM_0_5B_FILENAMES = (
    "moondream-0_5b-int8.mf",
    "moondream-0.5b-int8.mf",
    "moondream_0_5b_int8.mf",
)
