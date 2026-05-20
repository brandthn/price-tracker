from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple


REJECTION_MISSING_REQUIRED = "MISSING_REQUIRED_FIELD"
REJECTION_INVALID_CURRENCY = "INVALID_CURRENCY"
REJECTION_INVALID_COUNTRY = "INVALID_COUNTRY"
REJECTION_INVALID_PRICE = "INVALID_PRICE"
REJECTION_OUT_OF_RANGE_PRICE = "OUT_OF_RANGE_PRICE"
REJECTION_FUTURE_DATE = "FUTURE_DATE"
REJECTION_INVALID_PROOF_TYPE = "INVALID_PROOF_TYPE"

DEFAULT_ALLOWED_COUNTRIES = {
    "FR", "GP", "GF", "MQ", "RE", "YT", "PM", "MF", "BL", "WF", "NC", "PF"
}
DEFAULT_ALLOWED_CURRENCIES = {"EUR"}
DEFAULT_ALLOWED_PROOF_TYPES = {"RECEIPT", "PRICE_TAG", "PRICETAG", "SHOP_IMPORT"}

REQUIRED_FIELDS = {"id", "product_code", "price", "currency", "price_date"}


@dataclass(frozen=True)
class CleanerConfig:
    allowed_countries: set[str]
    allowed_currencies: set[str]
    allowed_proof_types: set[str]
    min_price_eur: Decimal
    max_price_eur: Decimal
    reference_date: date

    @classmethod
    def default(cls, reference_date: Optional[date] = None) -> "CleanerConfig":
        return cls(
            allowed_countries=DEFAULT_ALLOWED_COUNTRIES,
            allowed_currencies=DEFAULT_ALLOWED_CURRENCIES,
            allowed_proof_types=DEFAULT_ALLOWED_PROOF_TYPES,
            min_price_eur=Decimal("0.01"),
            max_price_eur=Decimal("500.00"),
            reference_date=reference_date or date.today(),
        )


def normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_country_code(value: Any) -> Optional[str]:
    text = normalize_text(value)
    return text.upper() if text else None


def normalize_currency(value: Any) -> Optional[str]:
    text = normalize_text(value)
    return text.upper() if text else None


def normalize_proof_type(value: Any) -> Optional[str]:
    text = normalize_text(value)
    if not text:
        return None
    text = text.upper().replace("-", "_").replace(" ", "_")
    return text


def parse_decimal_price(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", ".")
    text = re.sub(r"[^\d.\\-]", "", text)
    if text.count(".") > 1:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None

    candidates = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def iso_week_start(input_date: date) -> date:
    return input_date.fromisocalendar(input_date.isocalendar().year, input_date.isocalendar().week, 1)


def extract_store_brand(record: Dict[str, Any]) -> Optional[str]:
    candidates = [
        record.get("store_brand"),
        record.get("store_name"),
        record.get("location_osm_display_name"),
        record.get("location_osm_name"),
        record.get("banner"),
        record.get("chain"),
    ]
    for candidate in candidates:
        text = normalize_text(candidate)
        if text:
            cleaned = re.sub(r"\s+", " ", text)
            return cleaned[:200]
    return None


def has_required_fields(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    missing = []
    for field in REQUIRED_FIELDS:
        value = record.get(field)
        if value is None:
            missing.append(field)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field)
    return len(missing) == 0, sorted(missing)


def build_rejection_record(
    raw_record: Dict[str, Any],
    reason: str,
    details: Optional[str] = None,
    rejected_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    return {
        "id": raw_record.get("id"),
        "product_code": raw_record.get("product_code"),
        "reason": reason,
        "details": details,
        "currency": raw_record.get("currency"),
        "raw_price": raw_record.get("price"),
        "price_date": raw_record.get("price_date"),
        "country_code": raw_record.get("location_osm_address_country_code"),
        "proof_type": raw_record.get("proof_type"),
        "rejected_at": (rejected_at or datetime.utcnow()).isoformat(),
        "raw_payload": dict(raw_record),
    }


def clean_price_record(
    raw_record: Dict[str, Any],
    config: Optional[CleanerConfig] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    config = config or CleanerConfig.default()

    ok_required, missing_fields = has_required_fields(raw_record)
    if not ok_required:
        return None, build_rejection_record(
            raw_record,
            REJECTION_MISSING_REQUIRED,
            f"Missing required fields: {', '.join(missing_fields)}",
        )

    currency = normalize_currency(raw_record.get("currency"))
    if currency not in config.allowed_currencies:
        return None, build_rejection_record(
            raw_record,
            REJECTION_INVALID_CURRENCY,
            f"Unsupported currency: {currency}",
        )

    country_code = normalize_country_code(raw_record.get("location_osm_address_country_code"))
    if country_code not in config.allowed_countries:
        return None, build_rejection_record(
            raw_record,
            REJECTION_INVALID_COUNTRY,
            f"Unsupported country: {country_code}",
        )

    proof_type = normalize_proof_type(raw_record.get("proof_type"))
    if proof_type not in config.allowed_proof_types:
        return None, build_rejection_record(
            raw_record,
            REJECTION_INVALID_PROOF_TYPE,
            f"Unsupported proof type: {proof_type}",
        )

    price_value = parse_decimal_price(raw_record.get("price"))
    if price_value is None:
        return None, build_rejection_record(
            raw_record,
            REJECTION_INVALID_PRICE,
            f"Could not parse price: {raw_record.get('price')}",
        )

    if not (config.min_price_eur <= price_value <= config.max_price_eur):
        return None, build_rejection_record(
            raw_record,
            REJECTION_OUT_OF_RANGE_PRICE,
            f"Price out of range: {price_value}",
        )

    price_date = parse_date(raw_record.get("price_date"))
    if price_date is None:
        return None, build_rejection_record(
            raw_record,
            REJECTION_MISSING_REQUIRED,
            "Invalid or missing price_date",
        )

    if price_date > config.reference_date:
        return None, build_rejection_record(
            raw_record,
            REJECTION_FUTURE_DATE,
            f"price_date {price_date.isoformat()} is in the future",
        )

    store_brand = extract_store_brand(raw_record)
    discount_price = parse_decimal_price(raw_record.get("price_without_discount"))
    is_discounted = bool(raw_record.get("price_is_discounted", False))

    cleaned = {
        "id": normalize_text(raw_record.get("id")),
        "product_code": normalize_text(raw_record.get("product_code")),
        "price_eur": float(price_value),
        "price_eur_decimal": str(price_value),
        "price_without_discount_eur": float(discount_price) if discount_price is not None else None,
        "price_is_discounted": is_discounted,
        "currency": currency,
        "price_date": price_date.isoformat(),
        "week_start_date": iso_week_start(price_date).isoformat(),
        "proof_type": proof_type,
        "country_code": country_code,
        "store_brand": store_brand,
        "location_id": normalize_text(raw_record.get("location_id")),
        "location_name": normalize_text(raw_record.get("location_name")),
        "location_osm_display_name": normalize_text(raw_record.get("location_osm_display_name")),
        "city": normalize_text(raw_record.get("location_osm_address_city")),
        "postcode": normalize_text(raw_record.get("location_osm_address_postcode")),
        "latitude": raw_record.get("location_osm_lat"),
        "longitude": raw_record.get("location_osm_lon"),
        "source": "openfoodfacts_open_prices",
        "ingested_at": datetime.utcnow().isoformat(),
        "raw_payload": dict(raw_record),
    }

    return cleaned, None


def clean_price_records(
    raw_records: Iterable[Dict[str, Any]],
    config: Optional[CleanerConfig] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    config = config or CleanerConfig.default()
    clean_rows: List[Dict[str, Any]] = []
    rejected_rows: List[Dict[str, Any]] = []

    total = 0
    rows_with_store_brand = 0

    for record in raw_records:
        total += 1
        clean_row, rejection_row = clean_price_record(record, config=config)
        if clean_row:
            clean_rows.append(clean_row)
            if clean_row.get("store_brand"):
                rows_with_store_brand += 1
        else:
            rejected_rows.append(rejection_row)

    accepted = len(clean_rows)
    rejected = len(rejected_rows)
    acceptance_rate = accepted / total if total else 0.0
    store_coverage_rate = rows_with_store_brand / accepted if accepted else 0.0

    metrics = {
        "total_records": total,
        "accepted_records": accepted,
        "rejected_records": rejected,
        "acceptance_rate": acceptance_rate,
        "store_brand_coverage_rate": store_coverage_rate,
        "rejections_by_reason": _count_rejections_by_reason(rejected_rows),
    }
    return clean_rows, rejected_rows, metrics


def _count_rejections_by_reason(rejected_rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rejected_rows:
        reason = row.get("reason", "UNKNOWN")
        counts[reason] = counts.get(reason, 0) + 1
    return counts