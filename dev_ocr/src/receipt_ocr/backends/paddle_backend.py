"""PaddleOCR-based concrete backend.

The first reference implementation. PaddleOCR is heavy to import, so we
do it lazily in :meth:`PaddleOcrBackend.__init__` rather than at module
import time.
"""

from __future__ import annotations

from typing import Any

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.exceptions import OcrBackendError


class PaddleOcrBackend(OcrBackend):
    """OCR backend backed by `PaddleOCR <https://github.com/PaddlePaddle/PaddleOCR>`_.

    Parameters
    ----------
    lang:
        Language code passed to PaddleOCR. French receipts are best
        served by ``"fr"`` but the underlying engine also accepts
        ``"en"``, ``"latin"`` etc.
    use_angle_cls:
        Whether to enable text-direction classification — useful for
        photographs where the receipt is slightly rotated.
    **paddle_kwargs:
        Extra keyword arguments forwarded to :class:`paddleocr.PaddleOCR`.
        Allows callers to override defaults without subclassing.
    """

    def __init__(
        self,
        lang: str = "fr",
        use_angle_cls: bool = True,
        **paddle_kwargs: Any,
    ) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "PaddleOCR is not installed. Install it with "
                "`pip install paddleocr paddlepaddle` to use PaddleOcrBackend."
            ) from exc

        self._lang = lang
        try:
            self._engine = PaddleOCR(
                use_angle_cls=use_angle_cls,
                lang=lang,
                show_log=False,
                **paddle_kwargs,
            )
        except Exception as exc:  # noqa: BLE001 — wrap any init failure
            raise OcrBackendError(
                f"Failed to initialise PaddleOCR: {exc}"
            ) from exc

    def extract_text(self, image_path: str) -> str:
        path = self._validate_image_path(image_path)

        try:
            raw = self._engine.ocr(str(path), cls=True)
        except Exception as exc:  # noqa: BLE001
            raise OcrBackendError(
                f"PaddleOCR failed on {image_path!r}: {exc}"
            ) from exc

        return self._flatten(raw)

    @staticmethod
    def _flatten(raw: Any) -> str:
        """Convert PaddleOCR's nested output into newline-separated text.

        PaddleOCR returns ``[[ [box, (text, conf)], ... ]]`` for a single
        image. We only care about the recognised text, preserving the
        line order returned by the engine.
        """
        if not raw:
            return ""

        # PaddleOCR ≥ 2.6 wraps results in a list — handle both shapes.
        pages = raw if isinstance(raw[0], list) else [raw]

        lines: list[str] = []
        for page in pages:
            if not page:
                continue
            for entry in page:
                if not entry or len(entry) < 2:
                    continue
                text_conf = entry[1]
                if isinstance(text_conf, (list, tuple)) and text_conf:
                    text = text_conf[0]
                    if isinstance(text, str) and text.strip():
                        lines.append(text.strip())
        return "\n".join(lines)
