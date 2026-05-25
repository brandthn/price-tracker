"""PP-OCRv4 mobile backend — optimised for speed (ONNX-first).

Targets ~1–3 s per image on mobile-class CPUs when using ONNX Runtime
with ``PP-OCRv4_mobile_det`` and a reduced input size (640 px default).

Initialisation tries engines in order until one works on the host:

1. ``paddle_static`` + ``PP-OCRv4_mobile_det`` (fastest on many hosts)
2. ``paddle_dynamic`` + default models (last-resort fallback; slower)

Note: PaddleOCR 3.5's public ``engine=`` parameter does not include
``onnxruntime`` (that is a per-model binding inside PaddleX). A dedicated
ONNX Runtime backend can be added later for true mobile deployment.
"""

from __future__ import annotations

import os
from typing import Any

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.paddle_backend import PaddleOcrBackend, _env_int
from receipt_ocr.constants import (
    DEFAULT_PPOCRV4_MAX_IMAGE_SIDE,
    ENV_PPOCRV4_MAX_IMAGE_SIDE,
    PADDLE_MOBILE_DET_MODEL,
)
from receipt_ocr.exceptions import OcrBackendError

# Engine profiles tried in order (fast / mobile-first).
_INIT_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "label": "ppocrv4-static-mobile",
        "engine": "paddle_static",
        "use_mobile_models": True,
    },
    {
        "label": "ppocrv4-dynamic-fallback",
        "engine": "paddle_dynamic",
        "use_mobile_models": False,
    },
)


class PpOcrV4MobileBackend(OcrBackend):
    """Fast OCR using PP-OCRv4 mobile weights via PaddleOCR 3.x.

    Wraps :class:`PaddleOcrBackend` internally and picks the first working
    engine profile on this machine.

    Parameters
    ----------
    lang:
        Language code for recognition (default ``"fr"``).
    max_image_side:
        Longest image side before OCR (default 640). Override via
        ``RECEIPT_OCR_PPOCRV4_MAX_IMAGE_SIDE``.
    **paddle_kwargs:
        Extra arguments forwarded to :class:`paddleocr.PaddleOCR`.
    """

    def __init__(
        self,
        lang: str | None = "fr",
        max_image_side: int | None = None,
        **paddle_kwargs: Any,
    ) -> None:
        side = (
            max_image_side
            if max_image_side is not None
            else _env_int(ENV_PPOCRV4_MAX_IMAGE_SIDE, DEFAULT_PPOCRV4_MAX_IMAGE_SIDE)
        )

        errors: list[str] = []
        inner: PaddleOcrBackend | None = None
        profile_label = ""

        for profile in _INIT_PROFILES:
            label = profile["label"]
            try:
                inner = PaddleOcrBackend(
                    lang=lang,
                    engine=profile["engine"],
                    use_mobile_models=profile["use_mobile_models"],
                    max_image_side=side,
                    **paddle_kwargs,
                )
                profile_label = label
                break
            except (OcrBackendError, ImportError) as exc:
                errors.append(f"{label}: {exc}")

        if inner is None:
            raise OcrBackendError(
                "Failed to initialise PpOcrV4MobileBackend. Tried:\n  "
                + "\n  ".join(errors)
            )

        self._inner = inner
        self.active_profile = profile_label
        self.failed_profiles = errors
        self.max_image_side = side
        self.det_model = (
            PADDLE_MOBILE_DET_MODEL
            if "mobile" in profile_label and "fallback" not in profile_label
            else "server (fallback)"
        )

    def extract_text(self, image_path: str) -> str:
        return self._inner.extract_text(image_path)
