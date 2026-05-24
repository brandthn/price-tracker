"""Moondream local provider (0.5B int8 by default)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.constants import (
    DEFAULT_VLM_MAX_IMAGE_SIDE,
    DEFAULT_VLM_MAX_TOKENS,
    DEFAULT_VLM_TEMPERATURE,
    ENV_VLM_MAX_IMAGE_SIDE,
    ENV_VLM_MAX_TOKENS,
    ENV_VLM_MODEL_PATH,
    ENV_VLM_TEMPERATURE,
    MOONDREAM_0_5B_FILENAMES,
    VlmModelName,
)
from receipt_ocr.exceptions import OcrBackendError
from receipt_ocr.vlm_image_prep import (
    VlmImageConfig,
    cleanup_temp_files,
    load_vlm_image_config_from_env,
    prepare_vlm_image,
)

# Set to True to allow Moondream Cloud (MOONDREAM_API_KEY) when no local .mf file.
_ENABLE_MOONDREAM_CLOUD = False

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


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def resolve_moondream_model_path(explicit: str | Path | None = None) -> Path | None:
    """Locate a local ``.mf`` weights file, or return ``None`` if not found."""
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
    """Moondream VLM — local ``.mf`` weights only (cloud fallback disabled)."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        max_image_side: int | None = None,
        image_config: VlmImageConfig | None = None,
    ) -> None:
        self._model_id = VlmModelName.MOONDREAM_0_5B.value
        self._image_config = image_config or load_vlm_image_config_from_env()
        if max_image_side is not None:
            self._image_config = VlmImageConfig(
                max_image_side=max_image_side,
                crop_mode=self._image_config.crop_mode,
                crop_margin=self._image_config.crop_margin,
                jpeg_quality=self._image_config.jpeg_quality,
            )
        self._local_path = resolve_moondream_model_path(model_path)
        self._temperature = _env_float(ENV_VLM_TEMPERATURE, DEFAULT_VLM_TEMPERATURE)
        self._max_tokens = _env_int(ENV_VLM_MAX_TOKENS, DEFAULT_VLM_MAX_TOKENS)
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
            elif _ENABLE_MOONDREAM_CLOUD:
                api_key = os.environ.get("MOONDREAM_API_KEY")
                if api_key:
                    self._model = md.vl(api_key=api_key)
                else:
                    raise OcrBackendError(self._missing_local_weights_message())
            else:
                raise OcrBackendError(self._missing_local_weights_message())
        except OcrBackendError:
            raise
        except Exception as exc:
            raise OcrBackendError(f"Failed to load Moondream model: {exc}") from exc

    @staticmethod
    def _missing_local_weights_message() -> str:
        return (
            "Moondream local weights not found. During development only local "
            "inference is enabled (cloud API fallback is off).\n"
            f"  1. Download moondream-0_5b-int8.mf and set {ENV_VLM_MODEL_PATH}, or\n"
            "  2. Place the file in data/models/ or ~/.cache/receipt_ocr/models/.\n"
            "See README (VLM backend section) for download links."
        )

    def analyze(self, image_path: str, prompt: str) -> str:
        return self.analyze_with_options(image_path, prompt, crop_mode=None)

    def analyze_with_options(
        self,
        image_path: str,
        prompt: str,
        *,
        crop_mode: str | None = None,
    ) -> str:
        path = OcrBackend._validate_image_path(image_path)
        inference_path, temp_files = prepare_vlm_image(
            path,
            self._image_config,
            crop_mode_override=crop_mode,
        )
        try:
            return self._query(inference_path, prompt)
        except OcrBackendError:
            raise
        except Exception as exc:
            raise OcrBackendError(
                f"Moondream inference failed on {image_path!r}: {exc}"
            ) from exc
        finally:
            cleanup_temp_files(temp_files)

    def analyze_queries(self, image_path: str, prompts: list[str]) -> list[str]:
        """Encode the image once, then run several prompts (multi-pass mode)."""
        path = OcrBackend._validate_image_path(image_path)
        inference_path, temp_files = prepare_vlm_image(path, self._image_config)
        try:
            encoded = self._encode_path(inference_path)
            return [self._query_encoded(encoded, prompt) for prompt in prompts]
        except OcrBackendError:
            raise
        except Exception as exc:
            raise OcrBackendError(
                f"Moondream multi-query failed on {image_path!r}: {exc}"
            ) from exc
        finally:
            cleanup_temp_files(temp_files)

    def _encode_path(self, image_path: str) -> Any:
        try:
            from PIL import Image
        except ImportError as exc:
            raise OcrBackendError("Pillow is required for MoondreamProvider.") from exc

        with Image.open(image_path) as pil_image:
            rgb = pil_image.convert("RGB")
            if hasattr(self._model, "encode_image"):
                return self._model.encode_image(rgb)
            return rgb

    def _query(self, image_path: str, prompt: str) -> str:
        encoded = self._encode_path(image_path)
        return self._query_encoded(encoded, prompt)

    def _query_encoded(self, encoded: Any, prompt: str) -> str:
        settings = {
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        try:
            result = self._model.query(encoded, prompt, settings=settings)
        except TypeError:
            result = self._model.query(encoded, prompt)

        answer = result.get("answer") if isinstance(result, dict) else result
        if answer is None:
            raise OcrBackendError("Moondream returned an empty response.")
        if not isinstance(answer, str):
            answer = str(answer)
        stripped = answer.strip()
        if not stripped:
            raise OcrBackendError("Moondream returned an empty answer string.")
        return stripped
