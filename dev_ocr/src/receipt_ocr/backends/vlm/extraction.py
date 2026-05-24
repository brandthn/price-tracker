"""VLM extraction orchestration — modes, retries, cleanup."""

from __future__ import annotations

import os
from dataclasses import dataclass

from receipt_ocr.backends.vlm.base import VlmProvider
from receipt_ocr.backends.vlm.multipass import run_multipass_extraction
from receipt_ocr.backends.vlm.prompts import (
    RECEIPT_EXTRACTION_PROMPT,
    RECEIPT_EXTRACTION_STRICT_PROMPT,
    RECEIPT_TRANSCRIPTION_PROMPT,
    RECEIPT_TRANSCRIPTION_STRICT_PROMPT,
)
from receipt_ocr.constants import (
    DEFAULT_VLM_MAX_RETRIES,
    DEFAULT_VLM_MODE,
    ENV_VLM_MAX_RETRIES,
    ENV_VLM_MODE,
    VlmCropMode,
    VlmMode,
)
from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError
from receipt_ocr.vlm_text_cleanup import clean_vlm_transcription
from receipt_ocr.vlm_validate import validate_vlm_output


@dataclass(frozen=True)
class VlmAttempt:
    prompt: str
    crop_mode: str | None = None


def load_vlm_mode() -> str:
    raw = os.environ.get(ENV_VLM_MODE, DEFAULT_VLM_MODE)
    return raw.strip().lower() if raw else DEFAULT_VLM_MODE


def load_max_retries() -> int:
    raw = os.environ.get(ENV_VLM_MAX_RETRIES)
    if raw is None or not raw.strip():
        return DEFAULT_VLM_MAX_RETRIES
    try:
        return max(0, int(raw.strip()))
    except ValueError:
        return DEFAULT_VLM_MAX_RETRIES


def run_vlm_extraction(provider: VlmProvider, image_path: str) -> str:
    """Execute configured VLM mode with validation and retries."""
    mode = load_vlm_mode()
    max_retries = load_max_retries()
    attempts = _build_attempts(mode, max_retries)

    last_output = ""
    last_reason = "unknown"

    for attempt in attempts:
        try:
            raw = _run_single(provider, image_path, mode, attempt)
        except OcrBackendError:
            raise
        except Exception as exc:
            raise OcrBackendError(f"VLM extraction failed on {image_path!r}: {exc}") from exc

        output = _post_process(mode, raw)
        last_output = output
        result = validate_vlm_output(mode, output)
        if result.ok:
            return output
        last_reason = result.reason

    snippet = last_output[:200].replace("\n", " ")
    raise ReceiptParseError(
        f"VLM {mode!r} output failed validation after {len(attempts)} attempt(s) "
        f"({last_reason}). Last output snippet: {snippet!r}"
    )


def _run_single(
    provider: VlmProvider,
    image_path: str,
    mode: str,
    attempt: VlmAttempt,
) -> str:
    if mode == VlmMode.MULTIPASS.value:
        return run_multipass_extraction(provider, image_path)

    if hasattr(provider, "analyze_with_options"):
        return provider.analyze_with_options(  # type: ignore[attr-defined]
            image_path,
            attempt.prompt,
            crop_mode=attempt.crop_mode,
        )
    return provider.analyze(image_path, attempt.prompt)


def _post_process(mode: str, raw: str) -> str:
    if mode == VlmMode.TRANSCRIBE.value:
        return clean_vlm_transcription(raw)
    return raw.strip()


def _build_attempts(mode: str, max_retries: int) -> list[VlmAttempt]:
    total = max(1, max_retries + 1)
    attempts: list[VlmAttempt] = []

    if mode == VlmMode.TRANSCRIBE.value:
        prompts = [RECEIPT_TRANSCRIPTION_PROMPT, RECEIPT_TRANSCRIPTION_STRICT_PROMPT]
        crops = [None, VlmCropMode.CENTER.value]
    elif mode == VlmMode.JSON.value:
        prompts = [RECEIPT_EXTRACTION_PROMPT, RECEIPT_EXTRACTION_STRICT_PROMPT]
        crops = [None, VlmCropMode.CENTER.value]
    else:
        return [VlmAttempt(prompt="", crop_mode=None)]

    for index in range(total):
        prompt = prompts[min(index, len(prompts) - 1)]
        crop = crops[min(index, len(crops) - 1)]
        attempts.append(VlmAttempt(prompt=prompt, crop_mode=crop))
    return attempts
