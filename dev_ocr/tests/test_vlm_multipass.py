"""Tests for multi-pass VLM merge logic."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from receipt_ocr.backends.vlm.multipass import run_multipass_extraction
from receipt_ocr.vlm_parse import merge_partial_tickets


def test_merge_partial_tickets():
    merged = merge_partial_tickets(
        [
            {"chaine_supermarche": "SUPER U", "adresse": "Paris"},
            {"date": "20240315 14:30"},
            {"produits": [{"nom_produit": "LAIT", "prix_unitaire_ou_kg": 1.09, "unites": 1}]},
        ]
    )
    ticket = merged["ticket"]
    assert ticket["chaine_supermarche"] == "SUPER U"
    assert ticket["date"] == "20240315 14:30"
    assert len(ticket["produits"]) == 1


def test_run_multipass_extraction_merges_answers():
    provider = MagicMock()
    provider.analyze_queries.return_value = [
        '{"chaine_supermarche":"LECLERC","adresse":"Nantes"}',
        '{"date":"20240315 14:30"}',
        '{"produits":[{"nom_produit":"PAIN","prix_unitaire_ou_kg":1.2,"unites":1}]}',
    ]
    result = run_multipass_extraction(provider, "any.jpg")
    assert "LECLERC" in result
    assert "PAIN" in result
    provider.analyze_queries.assert_called_once()
