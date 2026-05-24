"""Quality checks for VLM outputs — drives retry logic."""

from __future__ import annotations

import re
from dataclasses import dataclass

from receipt_ocr.constants import VlmMode
from receipt_ocr.vlm_parse import try_parse_vlm_json

_CHAT_MARKERS = (
    "note:",
    "the image shows",
    "i think",
    "newspaper",
    "this image",
    " cette image",
    "je pense",
)
_STORE_BAD_CHARS = re.compile(r"[(){}]|^(?:here|note|the image)", re.IGNORECASE)


@dataclass(frozen=True)
class VlmValidationResult:
    ok: bool
    reason: str = ""


def validate_vlm_output(mode: str, text: str) -> VlmValidationResult:
    """Return whether ``text`` is acceptable for the given extraction mode."""
    if not text or not text.strip():
        return VlmValidationResult(False, "empty output")

    if mode == VlmMode.TRANSCRIBE.value:
        return _validate_transcription(text)
    if mode == VlmMode.JSON.value:
        return _validate_json(text)
    if mode == VlmMode.MULTIPASS.value:
        return _validate_json(text)
    return VlmValidationResult(True)


def _validate_transcription(text: str) -> VlmValidationResult:
    lowered = text.lower()
    for marker in _CHAT_MARKERS:
        if marker in lowered:
            return VlmValidationResult(False, f"chatty output ({marker})")

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return VlmValidationResult(False, "transcription too short")

    if text.strip().startswith("{") and '"ticket"' in text:
        return VlmValidationResult(False, "model returned JSON instead of transcription")

    return VlmValidationResult(True)


def _validate_json(text: str) -> VlmValidationResult:
    parsed = try_parse_vlm_json(text)
    if parsed is None:
        return VlmValidationResult(False, "invalid or missing ticket JSON")

    ticket = parsed["ticket"]
    chain = ticket.get("chaine_supermarche", "")
    products = ticket.get("produits") or []
    if not chain and not products:
        return VlmValidationResult(False, "empty ticket")

    if chain and not looks_like_store_name(chain):
        return VlmValidationResult(False, "invalid chaine_supermarche")

    return VlmValidationResult(True)


def looks_like_store_name(value: str) -> bool:
    """Heuristic: reject explanatory / chatty chain names."""
    stripped = value.strip()
    if not stripped:
        return True
    if len(stripped) > 80:
        return False
    lowered = stripped.lower()
    for marker in _CHAT_MARKERS:
        if marker in lowered:
            return False
    if _STORE_BAD_CHARS.search(stripped):
        return False
    return True
