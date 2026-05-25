"""Groq cloud vision provider (Llama 4 Scout) for receipt JSON extraction."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.backends.vlm.extraction import load_vlm_mode
from receipt_ocr.constants import (
    DEFAULT_GROQ_MAX_TOKENS,
    DEFAULT_GROQ_MODEL,
    DEFAULT_VLM_TEMPERATURE,
    ENV_GROQ_API_KEY,
    ENV_GROQ_API_KEY_LEGACY,
    ENV_GROQ_MODEL,
    ENV_VLM_MAX_TOKENS,
    ENV_VLM_MODE,
    ENV_VLM_TEMPERATURE,
    GROQ_BASE64_MAX_BYTES,
    VlmModelName,
    VlmMode,
)
from receipt_ocr.exceptions import OcrBackendError
from receipt_ocr.vlm_image_prep import (
    VlmImageConfig,
    cleanup_temp_files,
    load_vlm_image_config_from_env,
    prepare_vlm_image,
)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def resolve_groq_api_key() -> str:
    """Return Groq API key from ``GROQ_API_KEY`` or legacy ``groq_key``."""
    for name in (ENV_GROQ_API_KEY, ENV_GROQ_API_KEY_LEGACY):
        raw = os.environ.get(name)
        if raw and raw.strip():
            return raw.strip().strip('"').strip("'")
    raise OcrBackendError(
        f"Groq API key not found. Set {ENV_GROQ_API_KEY} or {ENV_GROQ_API_KEY_LEGACY} "
        "in the environment or in a .env file at the project root."
    )


def _require_json_vlm_mode() -> None:
    mode = load_vlm_mode()
    if mode != VlmMode.JSON.value:
        raise OcrBackendError(
            f"GroqProvider requires {ENV_VLM_MODE}={VlmMode.JSON.value!r} "
            f"(got {mode!r}). Transcribe and multipass modes are not supported."
        )


def _image_to_data_url(image_path: str) -> str:
    path = Path(image_path)
    raw = path.read_bytes()
    if len(raw) > GROQ_BASE64_MAX_BYTES:
        raise OcrBackendError(
            f"Prepared image exceeds Groq base64 size limit ({len(raw)} bytes > "
            f"{GROQ_BASE64_MAX_BYTES}). Lower RECEIPT_VLM_MAX_IMAGE_SIDE or "
            "RECEIPT_VLM_JPEG_QUALITY."
        )
    encoded = base64.b64encode(raw).decode("ascii")
    suffix = path.suffix.lower()
    mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64,{encoded}"


class GroqProvider(VlmProvider):
    """Receipt extraction via Groq vision API (JSON mode only)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        image_config: VlmImageConfig | None = None,
    ) -> None:
        _require_json_vlm_mode()
        self._model_id = VlmModelName.GROQ_LLAMA4_SCOUT.value
        self._api_key = api_key or resolve_groq_api_key()
        self._groq_model = (
            model or os.environ.get(ENV_GROQ_MODEL) or DEFAULT_GROQ_MODEL
        ).strip()
        self._image_config = image_config or load_vlm_image_config_from_env()
        self._temperature = _env_float(ENV_VLM_TEMPERATURE, DEFAULT_VLM_TEMPERATURE)
        self._max_tokens = _env_int(ENV_VLM_MAX_TOKENS, DEFAULT_GROQ_MAX_TOKENS)
        self._client: object | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def groq_model(self) -> str:
        return self._groq_model

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client
        try:
            from groq import Groq
        except ImportError as exc:
            raise ImportError(
                "GroqProvider requires the 'groq' package. "
                "Install with: pip install -r requirements-groq.txt"
            ) from exc
        self._client = Groq(api_key=self._api_key)
        return self._client

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
            data_url = _image_to_data_url(inference_path)
            return self._chat(prompt, data_url)
        except OcrBackendError:
            raise
        except Exception as exc:
            raise OcrBackendError(
                f"Groq vision request failed on {image_path!r}: {exc}"
            ) from exc
        finally:
            cleanup_temp_files(temp_files)

    def _chat(self, prompt: str, image_data_url: str) -> str:
        client = self._get_client()
        try:
            completion = client.chat.completions.create(
                model=self._groq_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_data_url},
                            },
                        ],
                    }
                ],
                temperature=self._temperature,
                max_completion_tokens=self._max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise OcrBackendError(f"Groq API error: {exc}") from exc

        message = completion.choices[0].message
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        if not content or not str(content).strip():
            raise OcrBackendError("Groq returned an empty response.")
        return str(content).strip()
