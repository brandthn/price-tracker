"""Moondream local / cloud provider (0.5B int8 by default)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.constants import (
    DEFAULT_VLM_MAX_IMAGE_SIDE,
    ENV_VLM_MAX_IMAGE_SIDE,
    ENV_VLM_MODEL_PATH,
    MOONDREAM_0_5B_FILENAMES,
    VlmModelName,
)
from receipt_ocr.exceptions import OcrBackendError
from receipt_ocr.image_utils import resize_image_to_max_side

_ENV_MOONDREAM_API_KEY = "MOONDREAM_API_KEY"
_DEFAULT_MODEL_DIRS = (
    Path("data/models"),
    Path.home() / ".cache" / "receipt_ocr" / "models",
    Path.home() / ".cache" / "moondream",
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def resolve_moondream_model_path(explicit: str | Path | None = None) -> Path | None:
    """Locate a local ``.mf`` weights file, or return ``None`` for cloud mode."""
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        raise OcrBackendError(f"Moondream model file not found: {path}")

    env_path = os.environ.get(ENV_VLM_MODEL_PATH)
    if env_path:
        path = Path(env_path)
        if path.is_file():
            return path
        raise OcrBackendError(
            f"{ENV_VLM_MODEL_PATH} points to a missing file: {path}"
        )

    for directory in _DEFAULT_MODEL_DIRS:
        if not directory.is_dir():
            continue
        for filename in MOONDREAM_0_5B_FILENAMES:
            candidate = directory / filename
            if candidate.is_file():
                return candidate
    return None


class MoondreamProvider(VlmProvider):
    """Moondream VLM — local ``.mf`` weights or Moondream Cloud API.

    Parameters
    ----------
    model_path:
        Path to ``moondream-0_5b-int8.mf`` (or similar). Falls back to
        :envvar:`RECEIPT_VLM_MODEL_PATH` and common cache directories.
    api_key:
        Moondream Cloud API key. Falls back to :envvar:`MOONDREAM_API_KEY`.
        Used when no local weights file is found.
    max_image_side:
        Resize longest image side before inference.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        api_key: str | None = None,
        max_image_side: int | None = None,
    ) -> None:
        self._model_id = VlmModelName.MOONDREAM_0_5B.value
        self._max_image_side = (
            max_image_side
            if max_image_side is not None
            else _env_int(ENV_VLM_MAX_IMAGE_SIDE, DEFAULT_VLM_MAX_IMAGE_SIDE)
        )
        self._local_path = resolve_moondream_model_path(model_path)
        self._api_key = api_key or os.environ.get(_ENV_MOONDREAM_API_KEY)
        self._model: Any = None
        self._init_model()

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def uses_local_weights(self) -> bool:
        return self._local_path is not None

    def _init_model(self) -> None:
        try:
            import moondream as md
        except ImportError as exc:
            raise ImportError(
                "MoondreamProvider requires the 'moondream' package. "
                "Install with: pip install -r requirements-vlm.txt"
            ) from exc

        try:
            if self._local_path is not None:
                self._model = md.vl(model=str(self._local_path))
            elif self._api_key:
                self._model = md.vl(api_key=self._api_key)
            else:
                raise OcrBackendError(
                    "Moondream is not configured. Either:\n"
                    f"  1. Download moondream-0_5b-int8.mf and set {ENV_VLM_MODEL_PATH}, or\n"
                    "  2. Place the file in data/models/ or ~/.cache/receipt_ocr/models/, or\n"
                    f"  3. Set {_ENV_MOONDREAM_API_KEY} for Moondream Cloud.\n"
                    "See README (VLM backend section) for download links."
                )
        except OcrBackendError:
            raise
        except Exception as exc:
            raise OcrBackendError(f"Failed to load Moondream model: {exc}") from exc

    def analyze(self, image_path: str, prompt: str) -> str:
        path = OcrBackend._validate_image_path(image_path)
        inference_path, temp_path = resize_image_to_max_side(path, self._max_image_side)
        try:
            return self._query(inference_path, prompt)
        except OcrBackendError:
            raise
        except Exception as exc:
            raise OcrBackendError(
                f"Moondream inference failed on {image_path!r}: {exc}"
            ) from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _query(self, image_path: str, prompt: str) -> str:
        try:
            from PIL import Image
        except ImportError as exc:
            raise OcrBackendError("Pillow is required for MoondreamProvider.") from exc

        with Image.open(image_path) as pil_image:
            rgb = pil_image.convert("RGB")
            if hasattr(self._model, "encode_image"):
                encoded = self._model.encode_image(rgb)
                result = self._model.query(encoded, prompt)
            else:
                result = self._model.query(rgb, prompt)

        answer = result.get("answer") if isinstance(result, dict) else result
        if answer is None:
            raise OcrBackendError("Moondream returned an empty response.")
        if not isinstance(answer, str):
            answer = str(answer)
        stripped = answer.strip()
        if not stripped:
            raise OcrBackendError("Moondream returned an empty answer string.")
        return stripped
