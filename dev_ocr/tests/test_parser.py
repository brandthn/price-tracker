"""Unit tests for :class:`receipt_ocr.parser.ReceiptParser`.

These tests never touch a real OCR engine — they exercise the parser
against the in-memory fixtures in :mod:`tests.fixtures.sample_texts`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError
from receipt_ocr.parser import ReceiptParser
from tests.fixtures import sample_texts


def _make_backend(text: str = "") -> MagicMock:
    backend = MagicMock(spec=OcrBackend)
    backend.extract_text.return_value = text
    return backend


def test_parse_happy_path_returns_full_schema():
    backend = _make_backend(sample_texts.HAPPY_PATH)
    parser = ReceiptParser(backend)

    result = parser.parse("any.jpg")

    assert "ticket" in result
    ticket = result["ticket"]
    assert set(ticket.keys()) == {
        "date",
        "chaine_supermarche",
        "adresse",
        "produits",
    }

    assert ticket["date"] == "20240315 14:30"
    assert ticket["chaine_supermarche"] == "CARREFOUR MARKET"
    assert "75001 Paris" in ticket["adresse"]
    assert "rue de la République" in ticket["adresse"]

    names = [p["nom_produit"] for p in ticket["produits"]]
    assert "BANANES BIO" in names
    assert "PAIN COMPLET" in names
    assert "COCA COLA 1.5L" in names
    assert "CAMEMBERT" in names


def test_parse_ignores_totals_tva_and_payment_lines():
    backend = _make_backend(sample_texts.HAPPY_PATH)
    parser = ReceiptParser(backend)

    products = parser.parse("any.jpg")["ticket"]["produits"]
    names = [p["nom_produit"].lower() for p in products]

    for forbidden in ("total", "tva", "carte bancaire", "sous total"):
        assert not any(forbidden in n for n in names), (
            f"Footer line leaked into products: {names}"
        )


def test_parse_handles_quantity_lines():
    backend = _make_backend(sample_texts.WITH_QUANTITY)
    parser = ReceiptParser(backend)

    products = parser.parse("any.jpg")["ticket"]["produits"]

    yaourt = next(p for p in products if "YAOURT" in p["nom_produit"])
    assert yaourt["unites"] == 3
    assert yaourt["prix_unitaire_ou_kg"] == 1.29


def test_parse_handles_weight_lines():
    backend = _make_backend(sample_texts.WITH_WEIGHT)
    parser = ReceiptParser(backend)

    products = parser.parse("any.jpg")["ticket"]["produits"]

    pommes = next(p for p in products if "POMMES" in p["nom_produit"])
    assert pommes["prix_unitaire_ou_kg"] == 5.98
    assert pommes["unites"] == 1


def test_parse_text_empty_raises():
    parser = ReceiptParser(_make_backend())
    with pytest.raises(ReceiptParseError):
        parser.parse_text(sample_texts.EMPTY_TEXT)


def test_parse_missing_date_returns_empty_string():
    parser = ReceiptParser(_make_backend(sample_texts.MISSING_DATE))
    ticket = parser.parse("any.jpg")["ticket"]
    assert ticket["date"] == ""
    assert ticket["chaine_supermarche"] == "MONOPRIX"


def test_parse_only_header_noise_yields_empty_products_and_no_chain():
    parser = ReceiptParser(_make_backend(sample_texts.ONLY_HEADER_NOISE))
    ticket = parser.parse("any.jpg")["ticket"]
    assert ticket["produits"] == []
    # The fixture intentionally contains only noise lines, no real chain.
    assert ticket["chaine_supermarche"] == ""


def test_parse_propagates_backend_file_not_found():
    backend = MagicMock(spec=OcrBackend)
    backend.extract_text.side_effect = FileNotFoundError("nope")
    parser = ReceiptParser(backend)

    with pytest.raises(FileNotFoundError):
        parser.parse("missing.jpg")


def test_parse_propagates_ocr_backend_error():
    backend = MagicMock(spec=OcrBackend)
    backend.extract_text.side_effect = OcrBackendError("engine exploded")
    parser = ReceiptParser(backend)

    with pytest.raises(OcrBackendError):
        parser.parse("any.jpg")


def test_parse_wraps_unexpected_backend_exception():
    backend = MagicMock(spec=OcrBackend)
    backend.extract_text.side_effect = RuntimeError("boom")
    parser = ReceiptParser(backend)

    with pytest.raises(OcrBackendError):
        parser.parse("any.jpg")


def test_constructor_rejects_non_backend():
    with pytest.raises(TypeError):
        ReceiptParser(backend=object())  # type: ignore[arg-type]


def test_product_prices_are_rounded_to_two_decimals():
    backend = _make_backend(sample_texts.HAPPY_PATH)
    parser = ReceiptParser(backend)

    for product in parser.parse("any.jpg")["ticket"]["produits"]:
        price = product["prix_unitaire_ou_kg"]
        assert round(price, 2) == price


def test_date_format_yyyyMMdd_HHmm():
    backend = _make_backend(sample_texts.WITH_QUANTITY)
    parser = ReceiptParser(backend)

    date = parser.parse("any.jpg")["ticket"]["date"]
    assert len(date) == len("20240402 09:05")
    assert date[8] == " "
    assert date[11] == ":"
    assert date.startswith("2024")
