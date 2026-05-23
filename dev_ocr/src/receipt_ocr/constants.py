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
