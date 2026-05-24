"""Tests for :mod:`receipt_ocr.vlm_text_cleanup`."""

from __future__ import annotations

from receipt_ocr.vlm_text_cleanup import clean_vlm_transcription


def test_clean_vlm_transcription_strips_chatty_lines():
    raw = "Note: The image shows a receipt.\nCARREFOUR MARKET\n15/03/2024 14:30"
    cleaned = clean_vlm_transcription(raw)
    assert "Note:" not in cleaned
    assert "CARREFOUR MARKET" in cleaned


def test_clean_vlm_transcription_strips_markdown_fence():
    raw = "```json\n{\"ticket\":{}}\n```"
    cleaned = clean_vlm_transcription(raw)
    assert "```" not in cleaned
