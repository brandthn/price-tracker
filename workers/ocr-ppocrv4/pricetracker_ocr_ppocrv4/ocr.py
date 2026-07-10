"""Câblage du backend PP-OCRv4 mobile → ReceiptParser (schéma canonique).

``PpOcrV4MobileBackend`` essaie ``paddle_static`` + PP-OCRv4_mobile_det, puis
retombe sur ``paddle_dynamic``. Les modèles sont baked dans l'image (Dockerfile).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.exceptions import OcrBackendError, ReceiptParseError
from pricetracker_receipt_pipeline.parser import ReceiptParser

from .ppocr_v4_backend import PpOcrV4MobileBackend


class OcrProcessingError(Exception):
    """Échec déterministe du pipeline OCR (image illisible, sortie invalide)."""


def build_backend() -> OcrBackend:
    """Construit le backend une fois, au démarrage (lifespan)."""
    return PpOcrV4MobileBackend(lang="fr")


def run_ocr(backend: OcrBackend, image_bytes: bytes) -> dict:
    """OCR de ``image_bytes`` → dict canonique ``{"ticket": {...}}``."""
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp_path = Path(tmp.name)
    try:
        tmp.write(image_bytes)
        tmp.flush()
        tmp.close()
        return ReceiptParser(backend).parse(str(tmp_path))
    except (OcrBackendError, ReceiptParseError) as exc:
        raise OcrProcessingError(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
