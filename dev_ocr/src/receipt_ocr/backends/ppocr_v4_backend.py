"""PP-OCRv4 mobile — la variante rapide (~1-3 s/image sur un CPU correct),
poids mobile + entrée réduite à 640 px.

On essaie les profils dans l'ordre jusqu'à ce qu'un tienne sur la machine :
static+mobile d'abord, dynamic+modèles par défaut en dernier recours.

Le `engine=` public de PaddleOCR 3.5 ne propose pas onnxruntime (c'est un
binding par modèle dans PaddleX) — donc pas d'ONNX ici pour l'instant.
"""

from __future__ import annotations

from typing import Any

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.paddle_backend import PaddleOcrBackend
from receipt_ocr.constants import (
    DEFAULT_PPOCRV4_MAX_IMAGE_SIDE,
    ENV_PPOCRV4_MAX_IMAGE_SIDE,
    PADDLE_MOBILE_DET_MODEL,
)
from receipt_ocr.env import env_int
from receipt_ocr.exceptions import OcrBackendError

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
    def __init__(
        self,
        lang: str | None = "fr",
        max_image_side: int | None = None,
        **paddle_kwargs: Any,
    ) -> None:
        side = (
            max_image_side
            if max_image_side is not None
            else env_int(ENV_PPOCRV4_MAX_IMAGE_SIDE, DEFAULT_PPOCRV4_MAX_IMAGE_SIDE)
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
