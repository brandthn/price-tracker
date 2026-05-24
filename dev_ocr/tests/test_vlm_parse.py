"""Tests for :mod:`receipt_ocr.vlm_parse`."""

from __future__ import annotations

import pytest

from receipt_ocr.exceptions import ReceiptParseError
from receipt_ocr.vlm_parse import (
    normalize_vlm_ticket,
    strip_markdown_json_fence,
    try_parse_vlm_json,
)
from tests.fixtures import vlm_json


def test_strip_markdown_json_fence():
    inner = strip_markdown_json_fence(vlm_json.FENCED_VLM_JSON)
    assert inner.startswith("{")
    assert "```" not in inner


def test_try_parse_vlm_json_valid():
    result = try_parse_vlm_json(vlm_json.VALID_VLM_JSON)
    assert result is not None
    ticket = result["ticket"]
    assert ticket["date"] == "20240315 14:30"
    assert ticket["chaine_supermarche"] == "CARREFOUR MARKET"
    assert len(ticket["produits"]) == 2
    assert ticket["produits"][1]["prix_unitaire_ou_kg"] == 1.2
    assert ticket["produits"][1]["unites"] == 2


def test_try_parse_vlm_json_fenced():
    result = try_parse_vlm_json(vlm_json.FENCED_VLM_JSON)
    assert result is not None
    assert result["ticket"]["chaine_supermarche"] == "SUPER U"


def test_try_parse_vlm_json_returns_none_for_ocr_text():
    assert try_parse_vlm_json("CARREFOUR MARKET\n15/03/2024") is None


def test_extract_json_candidate_finds_embedded_object():
    from receipt_ocr.vlm_parse import extract_json_candidate

    text = 'Here is data {"ticket":{"date":"","chaine_supermarche":"A","adresse":"","produits":[]}}'
    candidate = extract_json_candidate(text)
    assert candidate.startswith("{")
    assert "ticket" in candidate


def test_normalize_vlm_ticket_rejects_bad_date():
    payload = {
        "ticket": {
            "date": "not-a-date",
            "chaine_supermarche": "X",
            "adresse": "",
            "produits": [],
        }
    }
    with pytest.raises(ReceiptParseError, match="invalid date"):
        normalize_vlm_ticket(payload)


def test_normalize_vlm_ticket_skips_empty_product_names():
    payload = {
        "ticket": {
            "date": "",
            "chaine_supermarche": "X",
            "adresse": "",
            "produits": [
                {"nom_produit": "", "prix_unitaire_ou_kg": 1.0, "unites": 1},
                {"nom_produit": "OK", "prix_unitaire_ou_kg": 2.5, "unites": 1},
            ],
        }
    }
    result = normalize_vlm_ticket(payload)
    assert len(result["ticket"]["produits"]) == 1
