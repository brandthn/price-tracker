"""Câblage du backend OCR-VLM from-scratch → ReceiptParser (schéma canonique).

Le checkpoint ``.pt`` et le ``tokenizer.json`` sont téléchargés depuis GCS au
démarrage (cf. ``main.lifespan``) puis lus via ``RECEIPT_VLM_MODEL_PATH`` et
``RECEIPT_VLM_TOKENIZER_PATH``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.exceptions import OcrBackendError, ReceiptParseError
from pricetracker_receipt_pipeline.parser import ReceiptParser

from .config import get_settings
from .scratch_backend import OcrVlmScratchBackend


class OcrProcessingError(Exception):
    """Échec déterministe du pipeline OCR (image illisible, sortie invalide)."""


def build_backend() -> OcrBackend:
    """Construit le backend une fois, au démarrage (lifespan). Charge le modèle."""
    max_len = get_settings().prt_scratch_max_len or None
    return OcrVlmScratchBackend(device="cpu", max_len=max_len)


def run_ocr(backend: OcrBackend, image_bytes: bytes) -> dict:
    """OCR de ``image_bytes`` → dict canonique ``{"ticket": {...}}``.

    Le backend émet déjà le JSON canonique : ``ReceiptParser`` le valide et le
    normalise (``try_parse_vlm_json``) sans passer par les heuristiques texte.
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
