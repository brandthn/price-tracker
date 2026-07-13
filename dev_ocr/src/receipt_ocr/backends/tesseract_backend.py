"""Backend Tesseract — pas encore fait."""

from __future__ import annotations

from receipt_ocr.backends.base import OcrBackend


class TesseractBackend(OcrBackend):
    def __init__(self) -> None:
        raise NotImplementedError(
            "TesseractBackend is a planned backend. "
            "Implement it by wrapping `pytesseract.image_to_string`."
        )

    def extract_text(self, image_path: str) -> str:  # pragma: no cover
        raise NotImplementedError
