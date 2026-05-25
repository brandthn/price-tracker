"""Tests for :mod:`receipt_ocr.vlm_validate`."""

from __future__ import annotations

from receipt_ocr.constants import VlmMode
from receipt_ocr.vlm_validate import looks_like_store_name, validate_vlm_output
from tests.fixtures import sample_texts, vlm_json


def test_validate_transcription_accepts_realistic_text():
    result = validate_vlm_output(VlmMode.TRANSCRIBE.value, sample_texts.HAPPY_PATH)
    assert result.ok


def test_validate_transcription_rejects_chatty_output():
    result = validate_vlm_output(
        VlmMode.TRANSCRIBE.value,
        "Note: The image shows a newspaper.",
    )
    assert not result.ok


def test_validate_json_rejects_chatty_chain():
    bad = """{"ticket":{"date":"","chaine_supermarche":"Note: not a store","adresse":"","produits":[]}}"""
    result = validate_vlm_output(VlmMode.JSON.value, bad)
    assert not result.ok


def test_validate_json_accepts_valid_payload():
    result = validate_vlm_output(VlmMode.JSON.value, vlm_json.VALID_VLM_JSON)
    assert result.ok


def test_looks_like_store_name():
    assert looks_like_store_name("SUPER U")
    assert not looks_like_store_name("Note: The image shows something")
