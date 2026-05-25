"""Stub for a future EasyOCR backend."""

from __future__ import annotations

from receipt_ocr.backends.base import OcrBackend


class EasyOcrBackend(OcrBackend):
    """Placeholder backend backed by EasyOCR (not yet implemented)."""

    def __init__(self) -> None:
        raise NotImplementedError(
            "EasyOcrBackend is a planned backend. "
            "Implement it by wrapping `easyocr.Reader.readtext`."
        )

    def extract_text(self, image_path: str) -> str:  # pragma: no cover
        raise NotImplementedError
