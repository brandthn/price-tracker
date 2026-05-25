"""Thin adapter around ``receipt_ocr.extract_receipt``."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from receipt_ocr import extract_receipt, reset_default_backend
from receipt_ocr.constants import ENV_VLM_MODE, ENV_VLM_MODEL, VlmModelName, VlmMode
from receipt_ocr.exceptions import ReceiptOcrError

ENV_RECEIPT_BACKEND = "RECEIPT_OCR_BACKEND"


class OcrProcessingError(Exception):
    """Wraps failures from the receipt_ocr package."""


def _configure_engine(engine: str) -> None:
    engine_lower = engine.strip().lower()
    if engine_lower == "groq":
        os.environ[ENV_RECEIPT_BACKEND] = "vlm"
        os.environ[ENV_VLM_MODEL] = VlmModelName.GROQ_LLAMA4_SCOUT.value
        os.environ[ENV_VLM_MODE] = VlmMode.JSON.value
    elif engine_lower == "paddleocr":
        os.environ[ENV_RECEIPT_BACKEND] = "paddle"
    elif engine_lower == "tesseract":
        os.environ[ENV_RECEIPT_BACKEND] = "tesseract"
    else:
        raise ValueError(f"Unsupported OCR engine: {engine!r}")
    reset_default_backend()


def run_ocr(image_bytes: bytes, engine: str = "groq") -> dict:
    """Write bytes to a temp file, call ``extract_receipt``, return the raw dict.

    ``GROQ_API_KEY`` must be set in the environment when ``engine='groq'``.
    Raises :class:`OcrProcessingError` on any :class:`ReceiptOcrError`.
    """
    _configure_engine(engine)

    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp_path = Path(tmp.name)
    try:
        tmp.write(image_bytes)
        tmp.flush()
        tmp.close()
        return extract_receipt(str(tmp_path))
    except ReceiptOcrError as exc:
        raise OcrProcessingError(str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
