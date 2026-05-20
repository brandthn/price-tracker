from datetime import date, timedelta

from shared.cleaner import (
    CleanerConfig,
    REJECTION_FUTURE_DATE,
    REJECTION_INVALID_COUNTRY,
    REJECTION_INVALID_CURRENCY,
    REJECTION_INVALID_PRICE,
    REJECTION_INVALID_PROOF_TYPE,
    REJECTION_MISSING_REQUIRED,
    REJECTION_OUT_OF_RANGE_PRICE,
    clean_price_record,
    clean_price_records,
    extract_store_brand,
    has_required_fields,
    iso_week_start,
    parse_date,
    parse_decimal_price,
)


def build_valid_record():
    return {
        "id": "row-1",
        "product_code": "3274080005003",
        "price": "2.59",
        "currency": "EUR",
        "price_date": "2026-05-10",
        "proof_type": "RECEIPT",
        "location_osm_address_country_code": "FR",
        "location_id": "store-1",
        "location_name": "Carrefour City Strasbourg",
        "location_osm_display_name": "Carrefour City Strasbourg",
        "location_osm_address_city": "Strasbourg",
        "location_osm_address_postcode": "67000",
        "location_osm_lat": 48.58,
        "location_osm_lon": 7.75,
        "price_is_discounted": False,
    }


def test_parse_decimal_price_from_string():
    assert str(parse_decimal_price("2.59")) == "2.59"


def test_parse_decimal_price_from_comma_string():
    assert str(parse_decimal_price("2,59")) == "2.59"


def test_parse_decimal_price_invalid():
    assert parse_decimal_price("abc") is None


def test_parse_date_iso():
    assert parse_date("2026-05-10").isoformat() == "2026-05-10"


def test_iso_week_start_is_monday():
    assert iso_week_start(date(2026, 5, 10)).weekday() == 0


def test_has_required_fields_ok():
    ok, missing = has_required_fields(build_valid_record())
    assert ok is True
    assert missing == []


def test_has_required_fields_missing():
    record = build_valid_record()
    record["price"] = ""
    ok, missing = has_required_fields(record)
    assert ok is False
    assert "price" in missing


def test_extract_store_brand_prefers_store_brand():
    record = build_valid_record()
    record["store_brand"] = "Monoprix"
    assert extract_store_brand(record) == "Monoprix"


def test_clean_price_record_valid():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    clean_row, rejection = clean_price_record(build_valid_record(), config)
    assert rejection is None
    assert clean_row["currency"] == "EUR"
    assert clean_row["country_code"] == "FR"
    assert clean_row["product_code"] == "3274080005003"


def test_clean_price_record_reject_missing_required():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    del record["product_code"]
    clean_row, rejection = clean_price_record(record, config)
    assert clean_row is None
    assert rejection["reason"] == REJECTION_MISSING_REQUIRED


def test_clean_price_record_reject_invalid_currency():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["currency"] = "USD"
    clean_row, rejection = clean_price_record(record, config)
    assert clean_row is None
    assert rejection["reason"] == REJECTION_INVALID_CURRENCY


def test_clean_price_record_reject_invalid_country():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["location_osm_address_country_code"] = "DE"
    clean_row, rejection = clean_price_record(record, config)
    assert clean_row is None
    assert rejection["reason"] == REJECTION_INVALID_COUNTRY


def test_clean_price_record_reject_invalid_price():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["price"] = "not-a-price"
    clean_row, rejection = clean_price_record(record, config)
    assert clean_row is None
    assert rejection["reason"] == REJECTION_INVALID_PRICE


def test_clean_price_record_reject_price_too_low():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["price"] = "0.001"
    clean_row, rejection = clean_price_record(record, config)
    assert clean_row is None
    assert rejection["reason"] == REJECTION_OUT_OF_RANGE_PRICE


def test_clean_price_record_reject_price_too_high():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["price"] = "999.99"
    clean_row, rejection = clean_price_record(record, config)
    assert clean_row is None
    assert rejection["reason"] == REJECTION_OUT_OF_RANGE_PRICE


def test_clean_price_record_reject_future_date():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["price_date"] = (date(2026, 5, 12) + timedelta(days=2)).isoformat()
    clean_row, rejection = clean_price_record(record, config)
    assert clean_row is None
    assert rejection["reason"] == REJECTION_FUTURE_DATE


def test_clean_price_record_reject_invalid_proof_type():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["proof_type"] = "MANUAL"
    clean_row, rejection = clean_price_record(record, config)
    assert clean_row is None
    assert rejection["reason"] == REJECTION_INVALID_PROOF_TYPE


def test_clean_price_record_normalizes_discount_fields():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["price_is_discounted"] = True
    record["price_without_discount"] = "3.10"
    clean_row, rejection = clean_price_record(record, config)
    assert rejection is None
    assert clean_row["price_is_discounted"] is True
    assert clean_row["price_without_discount_eur"] == 3.10


def test_clean_price_records_metrics():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    good = build_valid_record()
    bad = build_valid_record()
    bad["currency"] = "USD"

    clean_rows, rejected_rows, metrics = clean_price_records([good, bad], config=config)
    assert len(clean_rows) == 1
    assert len(rejected_rows) == 1
    assert metrics["total_records"] == 2
    assert metrics["accepted_records"] == 1
    assert metrics["rejected_records"] == 1
    assert metrics["acceptance_rate"] == 0.5


def test_clean_price_record_accept_shop_import():
    """SHOP_IMPORT est maintenant accepté (prix déclarés par les enseignes)."""
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["proof_type"] = "SHOP_IMPORT"
    clean_row, rejection = clean_price_record(record, config)
    assert rejection is None
    assert clean_row["proof_type"] == "SHOP_IMPORT"


def test_clean_price_record_reject_gdpr_request():
    """GDPR_REQUEST doit être rejeté — ce sont des archives personnelles, pas des prix."""
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    record = build_valid_record()
    record["proof_type"] = "GDPR_REQUEST"
    clean_row, rejection = clean_price_record(record, config)
    assert clean_row is None
    assert rejection["reason"] == REJECTION_INVALID_PROOF_TYPE


def test_clean_price_records_store_brand_coverage():
    config = CleanerConfig.default(reference_date=date(2026, 5, 12))
    r1 = build_valid_record()
    r2 = build_valid_record()
    r2["id"] = "row-2"
    r2["location_osm_display_name"] = None
    r2["location_name"] = None

    clean_rows, _, metrics = clean_price_records([r1, r2], config=config)
    assert len(clean_rows) == 2
    assert metrics["store_brand_coverage_rate"] == 0.5