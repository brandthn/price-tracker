"""Le parser hérité de dev_ocr produit toujours le schéma canonique."""

from __future__ import annotations

import json

import pytest

from pricetracker_receipt_pipeline.backends.base import OcrBackend
from pricetracker_receipt_pipeline.exceptions import ReceiptParseError
from pricetracker_receipt_pipeline.parser import ReceiptParser

HAPPY_PATH = """\
CARREFOUR MARKET
12 rue de la République
75001 Paris
Tel 01 23 45 67 89

15/03/2024 14:30

BANANES BIO              2,15 €
PAIN COMPLET             1,20 €
COCA COLA 1.5L           2,49 €

SOUS TOTAL               5,84
TOTAL TTC                5,84 €
CARTE BANCAIRE           5,84
"""


class _FakeBackend(OcrBackend):
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self, image_path: str) -> str:
        return self._text


def test_parse_returns_canonical_schema():
    result = ReceiptParser(_FakeBackend(HAPPY_PATH)).parse("any.jpg")

    ticket = result["ticket"]
    assert set(ticket) == {"date", "chaine_supermarche", "adresse", "produits"}
    assert ticket["date"] == "20240315 14:30"
    assert ticket["chaine_supermarche"] == "CARREFOUR MARKET"
    assert "75001 Paris" in ticket["adresse"]

    names = [p["nom_produit"] for p in ticket["produits"]]
    assert names == ["BANANES BIO", "PAIN COMPLET", "COCA COLA 1.5L"]
    assert all(set(p) == {"nom_produit", "prix_unitaire_ou_kg", "unites"} for p in ticket["produits"])


def test_parse_drops_totals_and_payment_lines():
    products = ReceiptParser(_FakeBackend(HAPPY_PATH)).parse("any.jpg")["ticket"]["produits"]
    names = " ".join(p["nom_produit"].lower() for p in products)
    for forbidden in ("total", "tva", "carte bancaire"):
        assert forbidden not in names


def test_parse_short_circuits_on_vlm_json():
    """Un backend qui renvoie déjà du JSON ticket court-circuite les heuristiques."""
    payload = json.dumps(
        {
            "ticket": {
                "date": "20240315 14:30",
                "chaine_supermarche": "LIDL",
                "adresse": "1 rue X",
                "produits": [{"nom_produit": "LAIT", "prix_unitaire_ou_kg": 1.05, "unites": 2}],
            }
        },
        ensure_ascii=False,
    )
    ticket = ReceiptParser(_FakeBackend(payload)).parse("any.jpg")["ticket"]

    assert ticket["chaine_supermarche"] == "LIDL"
    assert ticket["produits"] == [
        {"nom_produit": "LAIT", "prix_unitaire_ou_kg": 1.05, "unites": 2}
    ]


def test_parse_empty_text_raises():
    with pytest.raises(ReceiptParseError):
        ReceiptParser(_FakeBackend("   ")).parse("any.jpg")


def test_parser_rejects_non_backend():
    with pytest.raises(TypeError):
        ReceiptParser(object())  # type: ignore[arg-type]
