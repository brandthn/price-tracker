"""Stub for a future Vision-Language-Model backend.

The eventual implementation will send the image to a multimodal LLM
(e.g. GPT-4o, Gemini, Qwen2-VL) and ask it to transcribe the receipt.
"""

from __future__ import annotations

from receipt_ocr.backends.base import OcrBackend


class VlmBackend(OcrBackend):
    """Placeholder backend backed by a Vision-Language Model (not yet implemented)."""

    def __init__(self) -> None:
        raise NotImplementedError(
            "VlmBackend is a planned backend. "
            "Implement it by calling a multimodal LLM API and returning "
            "the transcribed text."
        )

    def extract_text(self, image_path: str) -> str:  # pragma: no cover
        raise NotImplementedError
