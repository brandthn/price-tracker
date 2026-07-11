"""Câblage du backend Groq → ReceiptParser (schéma canonique).

Un seul backend par worker : pas de registre, pas de sélection par env var.
``GroqProvider`` exige ``RECEIPT_VLM_MODE=json`` (posé par le déploiement).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.backends.vlm_backend import VlmBackend
from pricetracker_receipt_pipeline.exceptions import OcrBackendError, ReceiptParseError
from pricetracker_receipt_pipeline.parser import ReceiptParser

from .groq_provider import GroqProvider


class OcrProcessingError(Exception):
    """Échec déterministe du pipeline OCR (image illisible, sortie invalide)."""


def build_backend() -> OcrBackend:
    """Construit le backend une fois, au démarrage (lifespan)."""
    return VlmBackend(provider=GroqProvider())


def run_ocr(backend: OcrBackend, image_bytes: bytes) -> dict:
    """OCR de ``image_bytes`` → dict canonique ``{"ticket": {...}}``.

    Le pipeline travaille sur un chemin de fichier : on matérialise les octets
    téléchargés depuis GCS dans un fichier temporaire, supprimé ensuite.
    """
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
