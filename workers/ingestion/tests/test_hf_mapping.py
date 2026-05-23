"""Tests du mapping HF row → format attendu par cleaner."""

from __future__ import annotations

import pytest

from pricetracker_ingestion.hf_mapping import map_hf_row


def test_renames_date_to_price_date() -> None:
    out = map_hf_row({"date": "2026-05-17"})
    assert out["price_date"] == "2026-05-17"
    # `date` original conservé (idempotence + audit).
    assert out["date"] == "2026-05-17"


def test_idempotent_when_price_date_present() -> None:
    out = map_hf_row({"date": "2026-05-17", "price_date": "2025-01-01"})
    assert out["price_date"] == "2025-01-01"


@pytest.mark.parametrize(
    "input_country,expected_iso2",
    [
        ("France", "FR"),
        ("FRANCE", "FR"),
        ("Guadeloupe", "GP"),
        ("FR", "FR"),  # déjà ISO2
        ("FRA", "FR"),  # ISO3
        ("Atlantis", None),  # inconnu → pas d'inférence
    ],
)
def test_infers_country_code(input_country: str, expected_iso2: str | None) -> None:
    out = map_hf_row({"location_osm_address_country": input_country})
    assert out.get("location_osm_address_country_code") == expected_iso2


def test_does_not_overwrite_explicit_country_code() -> None:
    out = map_hf_row(
        {
            "location_osm_address_country": "France",
            "location_osm_address_country_code": "GP",
        }
    )
    assert out["location_osm_address_country_code"] == "GP"


def test_location_name_fallback() -> None:
    out = map_hf_row({"location_osm_display_name": "Lidl, Paris"})
    assert out["location_name"] == "Lidl, Paris"
