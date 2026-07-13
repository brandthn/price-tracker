"""Point d'entrée du package : extract_receipt(), et la fabrique de backends.

Le backend par défaut est mis en cache après le premier appel, sinon on
recharge les poids Paddle à chaque image (plusieurs secondes à chaque fois).
"""

from __future__ import annotations

import os
from typing import Optional

from receipt_ocr.env import load_project_env

load_project_env()

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.easyocr_backend import EasyOcrBackend
from receipt_ocr.backends.paddle_backend import PaddleOcrBackend
from receipt_ocr.backends.ppocr_v4_backend import PpOcrV4MobileBackend
from receipt_ocr.backends.tesseract_backend import TesseractBackend
from receipt_ocr.backends.vlm_backend import VlmBackend
from receipt_ocr.constants import ENV_BACKEND, BackendName
from receipt_ocr.parser import ReceiptParser

_BACKEND_REGISTRY: dict[BackendName, type[OcrBackend]] = {
    BackendName.PADDLE: PaddleOcrBackend,
    BackendName.PPOCRV4: PpOcrV4MobileBackend,
    BackendName.TESSERACT: TesseractBackend,
    BackendName.EASYOCR: EasyOcrBackend,
    BackendName.VLM: VlmBackend,
}

_cached_backend: OcrBackend | None = None
_cached_backend_name: BackendName | None = None


def _resolve_backend_name(name: Optional[str]) -> BackendName:
    if not name:
        return BackendName.PADDLE
    try:
        return BackendName(name.strip().lower())
    except ValueError as exc:
        valid = ", ".join(b.value for b in BackendName)
        raise ValueError(
            f"Unknown OCR backend {name!r}. Valid options: {valid}."
        ) from exc


def reset_default_backend() -> None:
    """Vide le cache — les tests en ont besoin entre deux backends."""
    global _cached_backend, _cached_backend_name
    _cached_backend = None
    _cached_backend_name = None


def build_backend(name: Optional[str] = None, *, force_new: bool = False) -> OcrBackend:
    """Résolution du backend : argument explicite, sinon RECEIPT_OCR_BACKEND,
    sinon paddle. L'instance est réutilisée tant que le nom ne change pas."""
    global _cached_backend, _cached_backend_name

    resolved = _resolve_backend_name(name or os.environ.get(ENV_BACKEND))
    if (
        not force_new
        and _cached_backend is not None
        and _cached_backend_name == resolved
    ):
        return _cached_backend

    backend = _BACKEND_REGISTRY[resolved]()
    _cached_backend = backend
    _cached_backend_name = resolved
    return backend


def extract_receipt(
    image_path: str,
    backend: Optional[OcrBackend] = None,
) -> dict:
    """Photo de ticket de caisse -> dict structuré (date, enseigne, produits)."""
    if backend is None:
        backend = build_backend()
    parser = ReceiptParser(backend)
    return parser.parse(image_path)
