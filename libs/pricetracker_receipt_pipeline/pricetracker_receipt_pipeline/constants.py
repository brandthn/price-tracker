"""Noms de champs, noms de backends, noms de variables d'env."""

from __future__ import annotations

from enum import Enum


class TicketField(str, Enum):
    TICKET = "ticket"
    DATE = "date"
    CHAINE = "chaine_supermarche"
    ADRESSE = "adresse"
    PRODUITS = "produits"


class ProductField(str, Enum):
    NOM = "nom_produit"
    PRIX = "prix_unitaire_ou_kg"
    UNITES = "unites"


OUTPUT_DATE_FORMAT = "%Y%m%d %H:%M"


class BackendName(str, Enum):
    PADDLE = "paddle"
    PPOCRV4 = "ppocrv4"
    TESSERACT = "tesseract"
    EASYOCR = "easyocr"
    VLM = "vlm"


ENV_BACKEND = "RECEIPT_OCR_BACKEND"
ENV_MAX_IMAGE_SIDE = "RECEIPT_OCR_MAX_IMAGE_SIDE"
ENV_CPU_THREADS = "RECEIPT_OCR_CPU_THREADS"

# Brider les threads évite que Paddle bouffe toute la machine sur un laptop.
DEFAULT_MAX_IMAGE_SIDE = 1280
DEFAULT_CPU_THREADS = 2

# PP-OCRv4 mobile : entrée plus petite, c'est le but (cible CPU).
DEFAULT_PPOCRV4_MAX_IMAGE_SIDE = 640
ENV_PPOCRV4_MAX_IMAGE_SIDE = "RECEIPT_OCR_PPOCRV4_MAX_IMAGE_SIDE"

PADDLE_MOBILE_DET_MODEL = "PP-OCRv4_mobile_det"


class VlmModelName(str, Enum):
    MOONDREAM_0_5B = "moondream-0.5b"
    GROQ_LLAMA4_SCOUT = "groq-llama4-scout"
    # Le VLM hybride maison. Il n'existe que côté déploiement, pas dans dev_ocr.
    RECEIPT_VLM_500M = "receipt-vlm-500m"


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

ENV_GROQ_API_KEY = "GROQ_API_KEY"
ENV_GROQ_API_KEY_LEGACY = "groq_key"
ENV_GROQ_MODEL = "RECEIPT_GROQ_MODEL"
DEFAULT_GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Groq refuse les payloads trop gros : on plafonne le base64 avant l'appel.
GROQ_BASE64_MAX_BYTES = 3_500_000

DEFAULT_VLM_MAX_IMAGE_SIDE = 1536
DEFAULT_VLM_MAX_RETRIES = 2
DEFAULT_VLM_CROP_MARGIN = 0.05
DEFAULT_VLM_JPEG_QUALITY = 95
DEFAULT_VLM_TEMPERATURE = 0.1
DEFAULT_VLM_MAX_TOKENS = 1024
DEFAULT_GROQ_MAX_TOKENS = 4096


class VlmMode(str, Enum):
    TRANSCRIBE = "transcribe"
    JSON = "json"
    MULTIPASS = "multipass"


class VlmCropMode(str, Enum):
    AUTO = "auto"
    CENTER = "center"
    OFF = "off"


DEFAULT_VLM_MODE = VlmMode.TRANSCRIBE.value

# Le nom du .mf change selon d'où on l'a téléchargé.
MOONDREAM_0_5B_FILENAMES = (
    "moondream-0_5b-int8.mf",
    "moondream-0.5b-int8.mf",
    "moondream_0_5b_int8.mf",
)
