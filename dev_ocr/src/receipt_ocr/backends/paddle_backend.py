"""PaddleOCR-based concrete backend (compatible with PaddleOCR ≥ 3.x).

Performance safeguards
----------------------
* **Image downscaling** before inference (longest side capped, default 1280 px).
* **CPU thread limits** via ``RECEIPT_OCR_CPU_THREADS`` (default 2).
* **MKL-DNN disabled** on Windows to avoid oneDNN crashes with ``paddle_static``.
* **``paddle_dynamic`` engine** by default — reliable on Windows.

Optional mobile detection models (``use_mobile_models=True``) require
``paddle_static`` and may not work on every Windows build; they are off
by default.

Set ``PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`` to skip PaddleX's slow
network check on cold start.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.constants import (
    DEFAULT_CPU_THREADS,
    DEFAULT_MAX_IMAGE_SIDE,
    ENV_CPU_THREADS,
    ENV_MAX_IMAGE_SIDE,
    PADDLE_MOBILE_DET_MODEL,
)
from receipt_ocr.exceptions import OcrBackendError

_MIN_SCORE: float = 0.5
"""Confidence threshold — texts below this are treated as noise."""


def _apply_cpu_thread_limits(threads: int) -> None:
    """Cap BLAS / OpenMP threads so OCR does not peg every CPU core."""
    if threads <= 0:
        return
    value = str(threads)
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "CPU_NUM_THREADS",
    ):
        os.environ.setdefault(var, value)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


class PaddleOcrBackend(OcrBackend):
    """OCR backend backed by `PaddleOCR <https://github.com/PaddlePaddle/PaddleOCR>`_.

    Parameters
    ----------
    lang:
        Language passed to PaddleOCR (``"fr"`` for French receipts).
    engine:
        Inference engine. ``None`` (default) picks ``paddle_dynamic``, or
        ``paddle_static`` when ``use_mobile_models=True``.
    max_image_side:
        Resize images so the longest side is at most this many pixels before
        OCR. Set to ``0`` to disable. Falls back to ``RECEIPT_OCR_MAX_IMAGE_SIDE``.
    cpu_threads:
        Limit parallel CPU threads. Falls back to ``RECEIPT_OCR_CPU_THREADS``.
    use_mobile_models:
        Use ``PP-OCRv4_mobile_det`` (requires ``paddle_static``). Off by
        default because ``paddle_static`` + oneDNN often fails on Windows.
    enable_mkldnn:
        Whether to enable Intel MKL-DNN. ``False`` by default for stability.
    use_doc_orientation_classify / use_doc_unwarping / use_textline_orientation:
        Extra PaddleX preprocessing stages — all off by default for speed.
    score_threshold:
        Drop recognised text below this confidence.
    **paddle_kwargs:
        Extra arguments forwarded to :class:`paddleocr.PaddleOCR`.
    """

    def __init__(
        self,
        lang: str | None = "fr",
        engine: str | None = None,
        max_image_side: int | None = None,
        cpu_threads: int | None = None,
        use_mobile_models: bool = False,
        enable_mkldnn: bool = False,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_textline_orientation: bool = False,
        score_threshold: float = _MIN_SCORE,
        **paddle_kwargs: Any,
    ) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "PaddleOCR is not installed. Install it with "
                "`pip install paddleocr paddlepaddle` to use PaddleOcrBackend."
            ) from exc

        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        # Avoid oneDNN-related crashes on Windows with paddle_static.
        os.environ.setdefault("FLAGS_use_mkldnn", "0")

        threads = (
            cpu_threads
            if cpu_threads is not None
            else _env_int(ENV_CPU_THREADS, DEFAULT_CPU_THREADS)
        )
        _apply_cpu_thread_limits(threads)

        self._max_image_side = (
            max_image_side
            if max_image_side is not None
            else _env_int(ENV_MAX_IMAGE_SIDE, DEFAULT_MAX_IMAGE_SIDE)
        )
        self._score_threshold = score_threshold
        self._PaddleOCR = PaddleOCR

        resolved_engine = engine or (
            "paddle_static" if use_mobile_models else "paddle_dynamic"
        )

        init_kwargs: dict[str, Any] = dict(
            engine=resolved_engine,
            enable_mkldnn=enable_mkldnn,
            use_doc_orientation_classify=use_doc_orientation_classify,
            use_doc_unwarping=use_doc_unwarping,
            use_textline_orientation=use_textline_orientation,
            **paddle_kwargs,
        )
        if lang is not None:
            init_kwargs["lang"] = lang
        if use_mobile_models and "text_detection_model_name" not in init_kwargs:
            init_kwargs["text_detection_model_name"] = PADDLE_MOBILE_DET_MODEL

        try:
            self._engine = self._create_engine(init_kwargs)
        except Exception as first_exc:  # noqa: BLE001
            if use_mobile_models and engine is None:
                fallback_kwargs = dict(
                    engine="paddle_dynamic",
                    enable_mkldnn=enable_mkldnn,
                    use_doc_orientation_classify=use_doc_orientation_classify,
                    use_doc_unwarping=use_doc_unwarping,
                    use_textline_orientation=use_textline_orientation,
                    **paddle_kwargs,
                )
                if lang is not None:
                    fallback_kwargs["lang"] = lang
                try:
                    self._engine = self._create_engine(fallback_kwargs)
                except Exception as second_exc:  # noqa: BLE001
                    raise OcrBackendError(
                        f"Failed to initialise PaddleOCR: {first_exc}; "
                        f"fallback also failed: {second_exc}"
                    ) from second_exc
            else:
                raise OcrBackendError(
                    f"Failed to initialise PaddleOCR: {first_exc}"
                ) from first_exc

    def _create_engine(self, init_kwargs: dict[str, Any]) -> Any:
        return self._PaddleOCR(**init_kwargs)

    def extract_text(self, image_path: str) -> str:
        """Run OCR on *image_path* and return recognised text, one line per row."""
        path = self._validate_image_path(image_path)
        ocr_path, temp_path = self._prepare_image(path)

        try:
            predict_kwargs: dict[str, Any] = {}
            if self._max_image_side > 0:
                predict_kwargs["text_det_limit_side_len"] = self._max_image_side
            results = self._engine.predict(ocr_path, **predict_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise OcrBackendError(
                f"PaddleOCR failed on {image_path!r}: {exc}"
            ) from exc
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

        return self._flatten(results, self._score_threshold)

    def _prepare_image(self, path: Path) -> tuple[str, Path | None]:
        """Downscale large images; return ``(path_for_ocr, temp_path_or_none)``."""
        if self._max_image_side <= 0:
            return str(path), None

        try:
            from PIL import Image
        except ImportError:
            return str(path), None

        try:
            with Image.open(path) as img:
                width, height = img.size
                longest = max(width, height)
                if longest <= self._max_image_side:
                    return str(path), None

                scale = self._max_image_side / longest
                new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
                converted = img.convert("RGB") if img.mode not in ("RGB", "L") else img
                resized = converted.resize(new_size, Image.Resampling.LANCZOS)

                tmp = tempfile.NamedTemporaryFile(
                    suffix=".jpg",
                    prefix="receipt_ocr_",
                    delete=False,
                )
                tmp_path = Path(tmp.name)
                tmp.close()
                resized.save(tmp_path, format="JPEG", quality=85, optimize=True)
                return str(tmp_path), tmp_path
        except Exception:
            return str(path), None

    @staticmethod
    def _flatten(results: Any, score_threshold: float = _MIN_SCORE) -> str:
        """Convert PaddleOCR 3.x ``predict()`` output to newline-separated text."""
        if not results:
            return ""

        lines: list[str] = []
        for page in results:
            if not page:
                continue
            texts: list[str] = page.get("rec_texts") or []
            scores: list[float] = page.get("rec_scores") or []
            padded_scores = list(scores) + [1.0] * max(0, len(texts) - len(scores))
            for text, score in zip(texts, padded_scores):
                if isinstance(text, str) and text.strip() and score >= score_threshold:
                    lines.append(text.strip())
        return "\n".join(lines)
