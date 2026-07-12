"""`try_parse_vlm_json` : le pont qui laisse passer les backends renvoyant du JSON."""

from __future__ import annotations

from pricetracker_receipt_pipeline.vlm_parse import try_parse_vlm_json


def test_accepts_markdown_fenced_json():
    text = '```json\n{"ticket": {"chaine_supermarche": "LIDL", "produits": []}}\n```'
    parsed = try_parse_vlm_json(text)
    assert parsed is not None
    assert parsed["ticket"]["chaine_supermarche"] == "LIDL"
    assert parsed["ticket"]["date"] == ""


def test_coerces_prices_units_and_date():
    text = (
        '{"ticket": {"date": "15/03/2024 14:30", "chaine_supermarche": "U",'
        ' "produits": [{"nom_produit": "LAIT", "prix_unitaire_ou_kg": "1,05 €", "unites": "3"}]}}'
    )
    ticket = try_parse_vlm_json(text)["ticket"]
    assert ticket["date"] == "20240315 14:30"
    assert ticket["produits"] == [
        {"nom_produit": "LAIT", "prix_unitaire_ou_kg": 1.05, "unites": 3}
    ]


def test_dedupes_repeated_products():
    item = '{"nom_produit": "LAIT", "prix_unitaire_ou_kg": 1.0, "unites": 1}'
    text = f'{{"ticket": {{"chaine_supermarche": "U", "produits": [{item}, {item}]}}}}'
    assert len(try_parse_vlm_json(text)["ticket"]["produits"]) == 1


def test_plain_ocr_text_is_not_json():
    assert try_parse_vlm_json("CARREFOUR\nBANANES 2,15 €") is None
