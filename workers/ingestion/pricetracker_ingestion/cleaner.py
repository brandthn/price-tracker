
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

# Codes de rejet
REJECTION_MISSING_REQUIRED = "MISSING_REQUIRED_FIELD"
REJECTION_INVALID_CURRENCY = "INVALID_CURRENCY"
REJECTION_INVALID_COUNTRY = "INVALID_COUNTRY"
REJECTION_INVALID_PROOF_TYPE = "INVALID_PROOF_TYPE"
REJECTION_INVALID_PRICE = "INVALID_PRICE"
REJECTION_OUT_OF_RANGE_PRICE = "OUT_OF_RANGE_PRICE"
REJECTION_INVALID_DATE = "INVALID_DATE"
REJECTION_FUTURE_DATE = "FUTURE_DATE"


REQUIRED_FIELDS = ("id", "product_code", "price", "currency", "price_date")


DEFAULT_ALLOWED_COUNTRIES = frozenset(
    {"FR", "GP", "GF", "MQ", "RE", "YT", "PM", "MF", "BL", "WF", "NC", "PF"}
)
DEFAULT_ALLOWED_CURRENCIES = frozenset({"EUR"})
DEFAULT_ALLOWED_PROOF_TYPES = frozenset({"RECEIPT", "PRICE_TAG", "PRICETAG", "SHOP_IMPORT"})


@dataclass(frozen=True)
class CleanerConfig:


    allowed_countries: frozenset[str] = DEFAULT_ALLOWED_COUNTRIES
    allowed_currencies: frozenset[str] = DEFAULT_ALLOWED_CURRENCIES
    allowed_proof_types: frozenset[str] = DEFAULT_ALLOWED_PROOF_TYPES
    min_price_eur: Decimal = field(default=Decimal("0.01"))
    max_price_eur: Decimal = field(default=Decimal("500.00"))

    reference_date: date | None = None





def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_upper(value: Any) -> str | None:
    text = _normalize_text(value)
    return text.upper() if text else None


def _normalize_proof_type(value: Any) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    return text.upper().replace("-", "_").replace(" ", "_")


def parse_decimal_price(value: Any) -> Decimal | None:

    if value is None:
        return None
    if isinstance(value, bool):

        return None
    if isinstance(value, int | float):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return Decimal(str(value))
    text = str(value).strip().replace(",", ".")

    text = re.sub(r"[^\d.\-]", "", text)
    if text.count(".") > 1 or not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
)


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def iso_week_start(d: date) -> date:

    iso = d.isocalendar()
    return date.fromisocalendar(iso.year, iso.week, 1)


def extract_store_brand_raw(record: dict[str, Any]) -> str | None:

    for key in (
        "store_brand",
        "store_name",
        "location_osm_display_name",
        "location_osm_name",
        "location_name",
    ):
        text = _normalize_text(record.get(key))
        if text:
            return re.sub(r"\s+", " ", text)[:200]
    return None


def _check_required(record: dict[str, Any]) -> list[str]:
    missing = []
    for fname in REQUIRED_FIELDS:
        value = record.get(fname)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(fname)
    return missing


def _build_rejection(
    raw: dict[str, Any],
    reason: str,
    details: str | None,
) -> dict[str, Any]:
    return {
        "id": _normalize_text(raw.get("id")),
        "product_code": _normalize_text(raw.get("product_code")),
        "reason": reason,
        "details": details,
        "currency": _normalize_text(raw.get("currency")),
        "raw_price": None if raw.get("price") is None else str(raw.get("price")),
        "raw_price_date": None if raw.get("price_date") is None else str(raw.get("price_date")),
        "country_code": _normalize_text(raw.get("location_osm_address_country_code")),
        "proof_type": _normalize_text(raw.get("proof_type")),
    }





def clean_price_record(
    raw: dict[str, Any],
    config: CleanerConfig,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:

    missing = _check_required(raw)
    if missing:
        return None, _build_rejection(
            raw,
            REJECTION_MISSING_REQUIRED,
            f"Missing required fields: {', '.join(missing)}",
        )

    currency = _normalize_upper(raw.get("currency"))
    if currency not in config.allowed_currencies:
        return None, _build_rejection(
            raw, REJECTION_INVALID_CURRENCY, f"Unsupported currency: {currency}"
        )

    country_code = _normalize_upper(raw.get("location_osm_address_country_code"))
    if country_code not in config.allowed_countries:
        return None, _build_rejection(
            raw, REJECTION_INVALID_COUNTRY, f"Unsupported country: {country_code}"
        )

    proof_type = _normalize_proof_type(raw.get("proof_type"))
    if proof_type not in config.allowed_proof_types:
        return None, _build_rejection(
            raw, REJECTION_INVALID_PROOF_TYPE, f"Unsupported proof type: {proof_type}"
        )

    if proof_type == "PRICETAG":
        proof_type = "PRICE_TAG"

    price = parse_decimal_price(raw.get("price"))
    if price is None:
        return None, _build_rejection(
            raw, REJECTION_INVALID_PRICE, f"Could not parse price: {raw.get('price')!r}"
        )
    if not (config.min_price_eur <= price <= config.max_price_eur):
        return None, _build_rejection(
            raw,
            REJECTION_OUT_OF_RANGE_PRICE,
            f"Price out of range [{config.min_price_eur}, {config.max_price_eur}]: {price}",
        )

    price_date = parse_date(raw.get("price_date"))
    if price_date is None:
        return None, _build_rejection(
            raw, REJECTION_INVALID_DATE, f"Invalid price_date: {raw.get('price_date')!r}"
        )
    if config.reference_date is not None and price_date > config.reference_date:
        return None, _build_rejection(
            raw,
            REJECTION_FUTURE_DATE,
            f"price_date {price_date.isoformat()} > reference {config.reference_date.isoformat()}",
        )

    discount_price = parse_decimal_price(raw.get("price_without_discount"))
    is_discounted_raw = raw.get("price_is_discounted")
    is_discounted = bool(is_discounted_raw) if is_discounted_raw is not None else None

    clean: dict[str, Any] = {
        "id": _normalize_text(raw.get("id")),
        "price_date": price_date,
        "week_start_date": iso_week_start(price_date),
        "product_code": _normalize_text(raw.get("product_code")),
        "price_eur": float(price),

        "price_eur_decimal": str(price),
        "price_without_discount_eur": float(discount_price) if discount_price is not None else None,
        "price_is_discounted": is_discounted,
        "currency": currency,
        "proof_type": proof_type,
        "country_code": country_code,
        "store_brand": extract_store_brand_raw(raw),
        "location_id": _normalize_text(raw.get("location_id")),
        "location_name": _normalize_text(raw.get("location_name")),
        "location_osm_display_name": _normalize_text(raw.get("location_osm_display_name")),

        "city": _normalize_text(raw.get("location_osm_address_city")),
        "postcode": _normalize_text(raw.get("location_osm_address_postcode")),
        "latitude": _safe_float(raw.get("location_osm_lat")),
        "longitude": _safe_float(raw.get("location_osm_lon")),
    }
    return clean, None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f
