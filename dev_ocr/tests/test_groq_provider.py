"""Groq provider guardrails (no live API — see test_groq_integration)."""

from __future__ import annotations

import pytest

from receipt_ocr.backends.vlm.registry import build_vlm_provider
from receipt_ocr.constants import ENV_VLM_MODE, VlmModelName, VlmMode
from receipt_ocr.exceptions import OcrBackendError


def test_groq_provider_rejects_non_json_mode(monkeypatch):
    monkeypatch.setenv(ENV_VLM_MODE, VlmMode.TRANSCRIBE.value)
    with pytest.raises(OcrBackendError, match="requires RECEIPT_VLM_MODE='json'"):
        build_vlm_provider(VlmModelName.GROQ_LLAMA4_SCOUT.value, api_key="test-key")


def test_groq_provider_rejects_multipass_mode(monkeypatch):
    monkeypatch.setenv(ENV_VLM_MODE, VlmMode.MULTIPASS.value)
    with pytest.raises(OcrBackendError, match="requires RECEIPT_VLM_MODE='json'"):
        build_vlm_provider(VlmModelName.GROQ_LLAMA4_SCOUT.value, api_key="test-key")
