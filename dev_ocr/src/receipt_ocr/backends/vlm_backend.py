"""Vision-Language-Model backend — delegates to a :class:`VlmProvider`."""

from __future__ import annotations

from typing import Any

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.backends.vlm.extraction import load_vlm_mode, run_vlm_extraction
from receipt_ocr.backends.vlm.registry import build_vlm_provider
from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError


class VlmBackend(OcrBackend):
    """Backend that extracts receipt data via local Moondream 0.5B.

    Set ``RECEIPT_OCR_BACKEND=vlm`` and ``RECEIPT_VLM_MODE=transcribe`` (default).
    Modes: ``transcribe`` | ``json`` | ``multipass``.
    """

    def __init__(
        self,
        provider: VlmProvider | None = None,
        model: str | None = None,
        **provider_kwargs: Any,
    ) -> None:
        self._provider = provider or build_vlm_provider(model, **provider_kwargs)

    @property
    def active_model(self) -> str:
        return self._provider.model_id

    @property
    def active_mode(self) -> str:
        return load_vlm_mode()

    def extract_text(self, image_path: str) -> str:
        """Run the VLM extraction pipeline and return text for :class:`ReceiptParser`."""
        try:
            return run_vlm_extraction(self._provider, image_path)
        except (OcrBackendError, ReceiptParseError):
            raise
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise OcrBackendError(
                f"VLM backend failed on {image_path!r}: {exc}"
            ) from exc
