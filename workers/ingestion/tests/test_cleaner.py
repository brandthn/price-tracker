"""Tests unitaires du cleaner : validation devise/pays/proof/prix/date."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from pricetracker_ingestion.cleaner import (
    REJECTION_FUTURE_DATE,
    REJECTION_INVALID_COUNTRY,
    REJECTION_INVALID_CURRENCY,
    REJECTION_INVALID_DATE,
    REJECTION_INVALID_PRICE,
    REJECTION_INVALID_PROOF_TYPE,
    REJECTION_MISSING_REQUIRED,
    REJECTION_OUT_OF_RANGE_PRICE,
    CleanerConfig,
    clean_price_record,
    iso_week_start,
    parse_date,
    parse_decimal_price,
)


@pytest.fixture
def config() -> CleanerConfig:
    return CleanerConfig(reference_date=date(2026, 5, 17))


def _valid_row(**overrides: object) -> dict[str, object]:
    base = {
        "id": "abc",
        "product_code": "3017620422003",
        "price": 3.49,
        "currency": "EUR",
        "price_date": "2026-05-10",
        "location_osm_address_country_code": "FR",
        "proof_type": "RECEIPT",
    }
    base.update(overrides)
    return base


def test_clean_happy_path(config: CleanerConfig) -> None:
    clean, rejection = clean_price_record(_valid_row(), config)
    assert rejection is None
    assert clean is not None
    assert clean["currency"] == "EUR"
    assert clean["country_code"] == "FR"
    assert clean["price_eur"] == 3.49
    assert clean["price_eur_decimal"] == "3.49"
    assert clean["price_date"] == date(2026, 5, 10)
    assert clean["week_start_date"] == date(2026, 5, 4)  # lundi de la semaine du 10/05


def test_clean_rejects_missing_required(config: CleanerConfig) -> None:
    row = _valid_row()
    row["price"] = None
    clean, rejection = clean_price_record(row, config)
    assert clean is None
    assert rejection is not None
    assert rejection["reason"] == REJECTION_MISSING_REQUIRED
    assert "price" in rejection["details"]


def test_clean_rejects_non_eur(config: CleanerConfig) -> None:
    _, rejection = clean_price_record(_valid_row(currency="USD"), config)
    assert rejection is not None
    assert rejection["reason"] == REJECTION_INVALID_CURRENCY


def test_clean_rejects_non_fr_country(config: CleanerConfig) -> None:
    _, rejection = clean_price_record(
        _valid_row(location_osm_address_country_code="DE"), config
    )
    assert rejection is not None
    assert rejection["reason"] == REJECTION_INVALID_COUNTRY


def test_clean_accepts_dom_tom(config: CleanerConfig) -> None:
    # DOM-TOM par défaut dans CleanerConfig.
    for code in ("GP", "MQ", "GF", "RE", "YT"):
        clean, _ = clean_price_record(
            _valid_row(location_osm_address_country_code=code), config
        )
        assert clean is not None
        assert clean["country_code"] == code


def test_clean_normalizes_pricetag_proof_type(config: CleanerConfig) -> None:
    """Le cleaner accepte PRICETAG mais canonicalise en PRICE_TAG."""
    clean, _ = clean_price_record(_valid_row(proof_type="PRICETAG"), config)
    assert clean is not None
    assert clean["proof_type"] == "PRICE_TAG"


def test_clean_rejects_unknown_proof_type(config: CleanerConfig) -> None:
    _, rejection = clean_price_record(_valid_row(proof_type="GUESS"), config)
    assert rejection is not None
    assert rejection["reason"] == REJECTION_INVALID_PROOF_TYPE


def test_clean_rejects_unparseable_price(config: CleanerConfig) -> None:
    _, rejection = clean_price_record(_valid_row(price="not a price"), config)
    assert rejection is not None
    assert rejection["reason"] == REJECTION_INVALID_PRICE


def test_clean_rejects_out_of_range_price(config: CleanerConfig) -> None:
    _, low = clean_price_record(_valid_row(price=0.001), config)
    _, high = clean_price_record(_valid_row(price=999.99), config)
    assert low is not None and low["reason"] == REJECTION_OUT_OF_RANGE_PRICE
    assert high is not None and high["reason"] == REJECTION_OUT_OF_RANGE_PRICE


def test_clean_rejects_invalid_date(config: CleanerConfig) -> None:
    _, rejection = clean_price_record(_valid_row(price_date="bogus"), config)
    assert rejection is not None
    assert rejection["reason"] == REJECTION_INVALID_DATE


def test_clean_rejects_future_date(config: CleanerConfig) -> None:
    _, rejection = clean_price_record(_valid_row(price_date="2030-01-01"), config)
    assert rejection is not None
    assert rejection["reason"] == REJECTION_FUTURE_DATE


def test_clean_handles_decimal_price_precision(config: CleanerConfig) -> None:
    clean, _ = clean_price_record(_valid_row(price="3,49"), config)
    assert clean is not None
    assert clean["price_eur_decimal"] == "3.49"


def test_clean_extracts_store_brand_from_display_name(config: CleanerConfig) -> None:
    row = _valid_row(location_osm_display_name="Lidl, 12 Rue de la Paix, Paris")
    clean, _ = clean_price_record(row, config)
    assert clean is not None
    assert clean["store_brand"].startswith("Lidl")


# ---------------------------------------------------------------------------
# Parsers utilitaires (couverture des cas limites)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (3.49, Decimal("3.49")),
        ("3.49", Decimal("3.49")),
        ("3,49", Decimal("3.49")),
        ("3,49 €", Decimal("3.49")),
        (None, None),
        ("not a price", None),
        (float("nan"), None),
        ("1.2.3", None),  # double point
        (True, None),  # bool → reject
    ],
)
def test_parse_decimal_price(raw: object, expected: Decimal | None) -> None:
    assert parse_decimal_price(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-05-17", date(2026, 5, 17)),
        ("2026/05/17", date(2026, 5, 17)),
        ("17/05/2026", date(2026, 5, 17)),
        ("2026-05-17T03:14:00", date(2026, 5, 17)),
        ("2026-05-17T03:14:00Z", date(2026, 5, 17)),
        ("bogus", None),
        (None, None),
        (date(2026, 5, 17), date(2026, 5, 17)),
    ],
)
def test_parse_date(raw: object, expected: date | None) -> None:
    assert parse_date(raw) == expected


def test_iso_week_start() -> None:
    # 2026-05-17 = dimanche → lundi 2026-05-11.
    assert iso_week_start(date(2026, 5, 17)) == date(2026, 5, 11)
    # Lundi → lui-même.
    assert iso_week_start(date(2026, 5, 11)) == date(2026, 5, 11)
