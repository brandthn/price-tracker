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


def test_coerce_vlm_date_from_french_short_format():
    payload = {
        "ticket": {
            "date": "15/10/24",
            "chaine_supermarche": "SUPER U",
            "adresse": "",
            "produits": [
                {"nom_produit": "LAIT", "prix_unitaire_ou_kg": 1.09, "unites": 1},
            ],
        }
    }
    result = normalize_vlm_ticket(payload)
    assert result["ticket"]["date"] == "20241015 00:00"


def test_normalize_vlm_ticket_coerces_fractional_unites():
    payload = {
        "ticket": {
            "date": "",
            "chaine_supermarche": "SUPER U",
            "adresse": "",
            "produits": [
                {"nom_produit": "RAISIN", "prix_unitaire_ou_kg": 2.79, "unites": 0.972},
            ],
        }
    }
    result = normalize_vlm_ticket(payload)
    assert result["ticket"]["produits"][0]["unites"] == 1


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


def test_dedupe_vlm_products_removes_exact_duplicates():
    payload = {
        "ticket": {
            "date": "20241015 12:40",
            "chaine_supermarche": "SUPER U",
            "adresse": "",
            "produits": [
                {"nom_produit": "RAISIN BLANC ITALIA", "prix_unitaire_ou_kg": 2.79, "unites": 1},
                {"nom_produit": "RAISIN BLANC ITALIA", "prix_unitaire_ou_kg": 2.79, "unites": 1},
                {"nom_produit": "RAISIN BLANC ITALIA", "prix_unitaire_ou_kg": 2.79, "unites": 1},
                {"nom_produit": "LAIT", "prix_unitaire_ou_kg": 1.09, "unites": 1},
            ],
        }
    }
    result = normalize_vlm_ticket(payload)
    names = [p["nom_produit"] for p in result["ticket"]["produits"]]
    assert names.count("RAISIN BLANC ITALIA") == 1
    assert len(result["ticket"]["produits"]) == 2


def test_loads_json_picks_richest_when_multiple_ticket_blobs():
    noisy = """\
{"ticket":{"date":"","chaine_supermarche":"","adresse":"","produits":[]}}
{"ticket":{"date":"20241015 12:40","chaine_supermarche":"SUPER U","adresse":"PARIS","produits":[{"nom_produit":"LAIT","prix_unitaire_ou_kg":1.09,"unites":1}]}}
"""
    from receipt_ocr.vlm_parse import loads_vlm_payload

    payload = loads_vlm_payload(noisy)
    assert payload is not None
    result = try_parse_vlm_json(noisy)
    assert result is not None
    assert result["ticket"]["chaine_supermarche"] == "SUPER U"
    assert len(result["ticket"]["produits"]) == 1


def test_normalize_vlm_ticket_skips_empty_product_names():
    payload = {
        "ticket": {
            "date": "",
            "chaine_supermarche": "X",
            "adresse": "",
            "produits": [
                {"nom_produit": "", "prix_unitaire_ou_kg": 1.0, "unites": 1},
                "not-a-dict",
                {"nom_produit": "OK", "prix_unitaire_ou_kg": 2.5, "unites": 1},
            ],
        }
    }
    result = normalize_vlm_ticket(payload)
    assert len(result["ticket"]["produits"]) == 1
