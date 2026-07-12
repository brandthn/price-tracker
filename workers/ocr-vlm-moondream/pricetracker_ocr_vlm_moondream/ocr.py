"""Câblage du backend Moondream → ReceiptParser (schéma canonique).

Les poids ``.mf`` sont téléchargés depuis GCS au démarrage (cf. ``main.lifespan``)
puis localisés par ``MoondreamProvider`` via ``RECEIPT_VLM_MODEL_PATH``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.backends.vlm_backend import VlmBackend
from pricetracker_receipt_pipeline.exceptions import OcrBackendError, ReceiptParseError
from pricetracker_receipt_pipeline.parser import ReceiptParser

from .moondream_provider import MoondreamProvider


class OcrProcessingError(Exception):
    """Échec déterministe du pipeline OCR (image illisible, sortie invalide)."""


def build_backend() -> OcrBackend:
    """Construit le backend une fois, au démarrage (lifespan). Charge les poids."""
    return VlmBackend(provider=MoondreamProvider())


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
