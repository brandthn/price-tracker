"""Vision-Language-Model backend — delegates to a :class:`VlmProvider`."""

from __future__ import annotations

from typing import Any

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.backends.vlm.prompts import RECEIPT_EXTRACTION_PROMPT
from receipt_ocr.backends.vlm.registry import build_vlm_provider
from receipt_ocr.exceptions import OcrBackendError


class VlmBackend(OcrBackend):
    """Backend that extracts receipt data via a multimodal LLM.

    The model is expected to return JSON matching the package schema
    (see :mod:`receipt_ocr.vlm_parse`). Set ``RECEIPT_OCR_BACKEND=vlm``
    and ``RECEIPT_VLM_MODEL=moondream-0.5b`` (default).

    Parameters
    ----------
    provider:
        Optional pre-built :class:`VlmProvider`. If omitted, one is
        created via :func:`receipt_ocr.backends.vlm.build_vlm_provider`.
    model:
        Registry id passed to the factory when ``provider`` is ``None``.
    **provider_kwargs:
        Forwarded to the provider constructor (e.g. ``model_path``).
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
        """Registry id of the loaded VLM (e.g. ``moondream-0.5b``)."""
        return self._provider.model_id

    def extract_text(self, image_path: str) -> str:
        """Run the VLM and return its raw output (expected: JSON string)."""
        try:
            return self._provider.analyze(image_path, RECEIPT_EXTRACTION_PROMPT)
        except OcrBackendError:
            raise
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise OcrBackendError(
                f"VLM backend failed on {image_path!r}: {exc}"
            ) from exc
