"""Parser tests for VLM JSON output."""

from __future__ import annotations

from unittest.mock import MagicMock

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.parser import ReceiptParser
from tests.fixtures import vlm_json


def test_parse_text_accepts_vlm_json():
    backend = MagicMock(spec=OcrBackend)
    backend.extract_text.return_value = vlm_json.VALID_VLM_JSON
    parser = ReceiptParser(backend)

    result = parser.parse("any.jpg")

    assert result["ticket"]["chaine_supermarche"] == "CARREFOUR MARKET"
    assert len(result["ticket"]["produits"]) == 2


def test_parse_text_vlm_json_bypasses_ocr_heuristics():
    backend = MagicMock(spec=OcrBackend)
    backend.extract_text.return_value = vlm_json.FENCED_VLM_JSON
    parser = ReceiptParser(backend)

    result = parser.parse("any.jpg")

    assert result["ticket"]["chaine_supermarche"] == "SUPER U"
    assert result["ticket"]["produits"][0]["nom_produit"] == "LAIT"
