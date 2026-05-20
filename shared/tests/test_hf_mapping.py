"""Tests du mapping Hugging Face → schéma cleaner."""

from shared.hf_mapping import hf_open_prices_row_to_cleaner_record


def test_maps_date_to_price_date():
    row = {"id": "1", "date": "2026-01-15", "location_osm_address_country": "FR"}
    out = hf_open_prices_row_to_cleaner_record(row)
    assert out["price_date"] == "2026-01-15"


def test_infers_country_code_from_france():
    row = {"location_osm_address_country": "France"}
    out = hf_open_prices_row_to_cleaner_record(row)
    assert out.get("location_osm_address_country_code") == "FR"


def test_preserves_explicit_iso2():
    row = {"location_osm_address_country_code": "DE"}
    out = hf_open_prices_row_to_cleaner_record(row)
    assert out.get("location_osm_address_country_code") == "DE"
