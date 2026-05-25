"""Tests for VLM extraction orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from receipt_ocr.backends.vlm.extraction import run_vlm_extraction
from receipt_ocr.constants import ENV_VLM_MODE, VlmMode
from receipt_ocr.exceptions import ReceiptParseError
from tests.fixtures import sample_texts


def test_run_vlm_extraction_transcribe_success(monkeypatch):
    monkeypatch.setenv(ENV_VLM_MODE, VlmMode.TRANSCRIBE.value)
    provider = MagicMock()
    provider.analyze_with_options.return_value = sample_texts.HAPPY_PATH
    text = run_vlm_extraction(provider, "any.jpg")
    assert "CARREFOUR MARKET" in text


def test_run_vlm_extraction_retries_on_chatty_output(monkeypatch):
    monkeypatch.setenv(ENV_VLM_MODE, VlmMode.TRANSCRIBE.value)
    monkeypatch.setenv("RECEIPT_VLM_MAX_RETRIES", "1")
    provider = MagicMock()
    provider.analyze_with_options.side_effect = [
        "Note: this is not useful",
        sample_texts.HAPPY_PATH,
    ]
    text = run_vlm_extraction(provider, "any.jpg")
    assert provider.analyze_with_options.call_count == 2
    assert "CARREFOUR MARKET" in text


def test_run_vlm_extraction_raises_after_failed_retries(monkeypatch):
    monkeypatch.setenv(ENV_VLM_MODE, VlmMode.TRANSCRIBE.value)
    monkeypatch.setenv("RECEIPT_VLM_MAX_RETRIES", "0")
    provider = MagicMock()
    provider.analyze_with_options.return_value = "Note: bad"
    with pytest.raises(ReceiptParseError):
        run_vlm_extraction(provider, "any.jpg")
