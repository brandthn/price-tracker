"""Contrôles qualité sur la sortie VLM — c'est ça qui déclenche les retries."""

from __future__ import annotations

from dataclasses import dataclass

from pricetracker_receipt_pipeline.constants import VlmMode
from pricetracker_receipt_pipeline.vlm_parse import _CHAT_MARKERS, looks_like_store_name, try_parse_vlm_json

@dataclass(frozen=True)
class VlmValidationResult:
    ok: bool
    reason: str = ""


def validate_vlm_output(mode: str, text: str) -> VlmValidationResult:
    """Est-ce que cette sortie est exploitable, vu le mode demandé ?"""
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
