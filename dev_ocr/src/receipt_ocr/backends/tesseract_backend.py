"""Stub for a future Tesseract backend.

The class exists so that the Strategy pattern is visible to readers and
so that the env-variable factory has a deterministic target to fail on
when ``tesseract`` is selected before this is implemented.
"""

from __future__ import annotations

from receipt_ocr.backends.base import OcrBackend


class TesseractBackend(OcrBackend):
    """Placeholder backend backed by Tesseract (not yet implemented)."""

    def __init__(self) -> None:
        raise NotImplementedError(
            "TesseractBackend is a planned backend. "
            "Implement it by wrapping `pytesseract.image_to_string`."
        )

    def extract_text(self, image_path: str) -> str:  # pragma: no cover
        raise NotImplementedError
