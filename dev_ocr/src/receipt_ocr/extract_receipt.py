"""Public entry point and backend factory.

This module exposes :func:`extract_receipt`, the one function users of
the package are expected to call. It also implements the env-variable
driven backend selection described in ``project_guidelines.md``.

The default backend is **cached** after the first call to
:func:`build_backend` / :func:`extract_receipt` so that heavy OCR models
are not reloaded on every image.
"""

from __future__ import annotations

import os
from typing import Optional

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.easyocr_backend import EasyOcrBackend
from receipt_ocr.backends.paddle_backend import PaddleOcrBackend
from receipt_ocr.backends.tesseract_backend import TesseractBackend
from receipt_ocr.backends.vlm_backend import VlmBackend
from receipt_ocr.constants import ENV_BACKEND, BackendName
from receipt_ocr.parser import ReceiptParser

_BACKEND_REGISTRY: dict[BackendName, type[OcrBackend]] = {
    BackendName.PADDLE: PaddleOcrBackend,
    BackendName.TESSERACT: TesseractBackend,
    BackendName.EASYOCR: EasyOcrBackend,
    BackendName.VLM: VlmBackend,
}

# Singleton cache — avoids reloading Paddle weights on every call.
_cached_backend: OcrBackend | None = None
_cached_backend_name: BackendName | None = None


def _resolve_backend_name(name: Optional[str]) -> BackendName:
    """Convert a string (env value or argument) into a :class:`BackendName`."""
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
    """Clear the cached default backend (useful in tests or after config changes)."""
    global _cached_backend, _cached_backend_name
    _cached_backend = None
    _cached_backend_name = None


def build_backend(name: Optional[str] = None, *, force_new: bool = False) -> OcrBackend:
    """Instantiate (or return cached) :class:`OcrBackend` for the given name.

    Resolution order for the name:

    1. The explicit ``name`` argument, if given.
    2. The ``RECEIPT_OCR_BACKEND`` environment variable.
    3. Default = ``"paddle"``.

    Unless ``force_new=True``, the same instance is reused across calls
    when the resolved backend name has not changed.
    """
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
    """Extract structured data from a French supermarket receipt image.

    Parameters
    ----------
    image_path:
        Path to the receipt image file.
    backend:
        Optional :class:`OcrBackend` instance. If ``None`` the cached
        default backend from :func:`build_backend` is used.

    Returns
    -------
    dict
        Dictionary matching the schema described in
        ``project_guidelines.md``.

    Raises
    ------
    FileNotFoundError
        If ``image_path`` does not exist.
    OcrBackendError
        If the OCR engine fails.
    ReceiptParseError
        If the OCR text cannot be parsed into a receipt.
    """
    if backend is None:
        backend = build_backend()
    parser = ReceiptParser(backend)
    return parser.parse(image_path)
