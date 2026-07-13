"""Backend PaddleOCR (>= 3.x).

Les garde-fous ici ne sont pas cosmétiques : sans downscale + bridage des
threads, une photo de ticket au format téléphone fait ramer la machine
entière. MKL-DNN est coupé et on reste sur `paddle_dynamic` parce que
`paddle_static` + oneDNN plante sur Windows.

PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True évite le check réseau de PaddleX
au démarrage à froid (lent).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.constants import (
    DEFAULT_CPU_THREADS,
    DEFAULT_MAX_IMAGE_SIDE,
    ENV_CPU_THREADS,
    ENV_MAX_IMAGE_SIDE,
    PADDLE_MOBILE_DET_MODEL,
)
from pricetracker_receipt_pipeline.env import env_int
from pricetracker_receipt_pipeline.exceptions import OcrBackendError

logger = logging.getLogger(__name__)

# En dessous, c'est du bruit (bords du ticket, fond de la photo).
_MIN_SCORE: float = 0.5


def _apply_cpu_thread_limits(threads: int) -> None:
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


class PaddleOcrBackend(OcrBackend):
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
        os.environ.setdefault("FLAGS_use_mkldnn", "0")

        threads = (
            cpu_threads
            if cpu_threads is not None
            else env_int(ENV_CPU_THREADS, DEFAULT_CPU_THREADS)
        )
        _apply_cpu_thread_limits(threads)

        self._max_image_side = (
            max_image_side
            if max_image_side is not None
            else env_int(ENV_MAX_IMAGE_SIDE, DEFAULT_MAX_IMAGE_SIDE)
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
            self._engine = self._PaddleOCR(**init_kwargs)
        except Exception as first_exc:
            # Les modèles mobile exigent paddle_static, qui casse sur pas mal
            # de builds Windows : on retombe sur dynamic plutôt que d'abandonner.
            if not (use_mobile_models and engine is None):
                raise OcrBackendError(
                    f"Failed to initialise PaddleOCR: {first_exc}"
                ) from first_exc

            fallback_kwargs = dict(init_kwargs, engine="paddle_dynamic")
            fallback_kwargs.pop("text_detection_model_name", None)
            try:
                self._engine = self._PaddleOCR(**fallback_kwargs)
            except Exception as second_exc:
                raise OcrBackendError(
                    f"Failed to initialise PaddleOCR: {first_exc}; "
                    f"fallback also failed: {second_exc}"
                ) from second_exc

    def extract_text(self, image_path: str) -> str:
        path = self._validate_image_path(image_path)
        ocr_path, temp_path = self._prepare_image(path)

        try:
            predict_kwargs: dict[str, Any] = {}
            if self._max_image_side > 0:
                predict_kwargs["text_det_limit_side_len"] = self._max_image_side
            results = self._engine.predict(ocr_path, **predict_kwargs)
        except Exception as exc:
            raise OcrBackendError(f"PaddleOCR failed on {image_path!r}: {exc}") from exc
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

        return self._flatten(results, self._score_threshold)

    def _prepare_image(self, path: Path) -> tuple[str, Path | None]:
        """Rend (chemin à donner à l'OCR, temp à supprimer après)."""
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
        except OSError as exc:
            # PIL ne sait pas ouvrir tous les formats que Paddle sait lire :
            # on tente quand même avec l'image d'origine, tant pis pour le downscale.
            logger.warning("resize impossible sur %s (%s), on passe l'original", path, exc)
            return str(path), None

    @staticmethod
    def _flatten(results: Any, score_threshold: float = _MIN_SCORE) -> str:
        if not results:
            return ""

        lines: list[str] = []
        for page in results:
            if not page:
                continue
            texts: list[str] = page.get("rec_texts") or []
            scores: list[float] = page.get("rec_scores") or []
            # Paddle rend parfois moins de scores que de textes.
            padded_scores = list(scores) + [1.0] * max(0, len(texts) - len(scores))
            for text, score in zip(texts, padded_scores):
                if isinstance(text, str) and text.strip() and score >= score_threshold:
                    lines.append(text.strip())
        return "\n".join(lines)
