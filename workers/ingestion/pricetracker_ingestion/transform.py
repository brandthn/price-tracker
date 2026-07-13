
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .cleaner import CleanerConfig, clean_price_record
from .enrichments import (
    check_discount_coherence,
    flag_iqr_outliers,
    normalize_store_brand,
    standardize_city,
    validate_ean,
)
from .hf_mapping import map_hf_row
from .logging import get_logger

logger = get_logger(__name__)


REJECTION_INVALID_EAN = "INVALID_EAN"
REJECTION_INCOHERENT_DISCOUNT = "INCOHERENT_DISCOUNT"


SOURCE_LABEL = "hf-open-prices"




SILVER_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("pipeline_run_date", pa.date32()),
        ("price_date", pa.date32()),
        ("week_start_date", pa.date32()),
        ("product_code", pa.string()),
        ("price_eur", pa.float64()),
        ("price_eur_decimal", pa.string()),
        ("price_without_discount_eur", pa.float64()),
        ("price_is_discounted", pa.bool_()),
        ("currency", pa.string()),
        ("proof_type", pa.string()),
        ("country_code", pa.string()),
        ("store_brand", pa.string()),
        ("store_brand_normalized", pa.string()),
        ("location_id", pa.string()),
        ("location_name", pa.string()),
        ("location_osm_display_name", pa.string()),
        ("city", pa.string()),
        ("postcode", pa.string()),
        ("latitude", pa.float64()),
        ("longitude", pa.float64()),
        ("iqr_outlier", pa.bool_()),
        ("source", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="UTC")),
        ("raw_payload", pa.string()),
    ]
)

REJECTIONS_SCHEMA = pa.schema(
    [

        pa.field("pipeline_run_date", pa.date32(), nullable=False),
        ("id", pa.string()),
        ("product_code", pa.string()),
        ("reason", pa.string()),
        ("details", pa.string()),
        ("currency", pa.string()),
        ("raw_price", pa.string()),
        ("raw_price_date", pa.string()),
        ("country_code", pa.string()),
        ("proof_type", pa.string()),
        ("rejected_at", pa.timestamp("us", tz="UTC")),
        ("raw_payload", pa.string()),
    ]
)





def _json_default(obj: Any) -> Any:

    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if hasattr(obj, "item"):
        return obj.item()
    return str(obj)


def _dumps_payload(raw: dict[str, Any]) -> str:
    return json.dumps(raw, ensure_ascii=False, default=_json_default)


def _empty_clean_table() -> pa.Table:
    return pa.table(
        {name: pa.array([], type=t) for name, t in zip(SILVER_SCHEMA.names, SILVER_SCHEMA.types, strict=True)},
        schema=SILVER_SCHEMA,
    )


def _empty_rejections_table() -> pa.Table:
    return pa.table(
        {name: pa.array([], type=t) for name, t in zip(REJECTIONS_SCHEMA.names, REJECTIONS_SCHEMA.types, strict=True)},
        schema=REJECTIONS_SCHEMA,
    )





def transform_open_prices(
    raw: pa.Table,
    *,
    pipeline_run_date: date,
    ingested_at: datetime | None = None,
    config: CleanerConfig | None = None,
) -> tuple[pa.Table, pa.Table, dict[str, Any]]:

    n_input = raw.num_rows
    ingested_at_ts = ingested_at or datetime.now(UTC)
    cleaner_config = config or CleanerConfig(reference_date=pipeline_run_date)

    if n_input == 0:
        logger.info("transform_empty_input")
        return _empty_clean_table(), _empty_rejections_table(), {
            "rows_input": 0,
            "rows_clean": 0,
            "rows_rejected": 0,
            "acceptance_rate": 0.0,
            "rejections_by_reason": {},
            "store_brand_coverage": 0.0,
            "iqr_outliers": 0,
        }

    clean_rows: list[dict[str, Any]] = []
    rejection_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    rejections_by_reason: dict[str, int] = {}

    raw_rows = raw.to_pylist()
    for raw_row in raw_rows:

        raw_payload_json = _dumps_payload(raw_row)
        mapped = map_hf_row(raw_row)

        clean, rejection = clean_price_record(mapped, config=cleaner_config)

        if rejection is not None:
            rejection["raw_payload"] = raw_payload_json
            rejection_rows.append(rejection)
            rejections_by_reason[rejection["reason"]] = (
                rejections_by_reason.get(rejection["reason"], 0) + 1
            )
            continue


        assert clean is not None
        ean_ok, ean_details = validate_ean(clean["product_code"])
        if not ean_ok:
            rejection_rows.append(
                _build_rejection_from_clean(
                    raw_row, clean, REJECTION_INVALID_EAN, ean_details, raw_payload_json
                )
            )
            rejections_by_reason[REJECTION_INVALID_EAN] = (
                rejections_by_reason.get(REJECTION_INVALID_EAN, 0) + 1
            )
            continue

        disc_ok, disc_details = check_discount_coherence(clean)
        if not disc_ok:
            rejection_rows.append(
                _build_rejection_from_clean(
                    raw_row, clean, REJECTION_INCOHERENT_DISCOUNT, disc_details, raw_payload_json
                )
            )
            rejections_by_reason[REJECTION_INCOHERENT_DISCOUNT] = (
                rejections_by_reason.get(REJECTION_INCOHERENT_DISCOUNT, 0) + 1
            )
            continue


        if clean["id"] in seen_ids:
            continue
        seen_ids.add(clean["id"])


        clean["store_brand_normalized"] = normalize_store_brand(clean["store_brand"])
        clean["city"] = standardize_city(clean["city"])
        clean["raw_payload"] = raw_payload_json
        clean_rows.append(clean)


    flag_iqr_outliers(clean_rows)


    for row in clean_rows:
        row["pipeline_run_date"] = pipeline_run_date
        row["ingested_at"] = ingested_at_ts
        row["source"] = SOURCE_LABEL

    for row in rejection_rows:
        row["pipeline_run_date"] = pipeline_run_date
        row["rejected_at"] = ingested_at_ts

    clean_table = _rows_to_table(clean_rows, SILVER_SCHEMA)
    rejections_table = _rows_to_table(rejection_rows, REJECTIONS_SCHEMA)

    n_clean = clean_table.num_rows
    n_rejected = rejections_table.num_rows
    n_iqr = sum(1 for r in clean_rows if r.get("iqr_outlier"))
    n_with_brand = sum(1 for r in clean_rows if r.get("store_brand_normalized"))

    metrics: dict[str, Any] = {
        "rows_input": n_input,
        "rows_clean": n_clean,
        "rows_rejected": n_rejected,
        "acceptance_rate": round(n_clean / n_input, 4) if n_input else 0.0,
        "rejections_by_reason": rejections_by_reason,
        "store_brand_coverage": round(n_with_brand / n_clean, 4) if n_clean else 0.0,
        "iqr_outliers": n_iqr,
    }
    logger.info("transform_done", **metrics)
    return clean_table, rejections_table, metrics


def _build_rejection_from_clean(
    raw_row: dict[str, Any],
    clean: dict[str, Any],
    reason: str,
    details: str | None,
    raw_payload_json: str,
) -> dict[str, Any]:

    return {
        "id": clean.get("id"),
        "product_code": clean.get("product_code"),
        "reason": reason,
        "details": details,
        "currency": clean.get("currency"),
        "raw_price": None if raw_row.get("price") is None else str(raw_row.get("price")),
        "raw_price_date": (
            None if raw_row.get("price_date") is None else str(raw_row.get("price_date"))
        ),
        "country_code": clean.get("country_code"),
        "proof_type": clean.get("proof_type"),
        "raw_payload": raw_payload_json,
    }


def _rows_to_table(rows: list[dict[str, Any]], schema: pa.Schema) -> pa.Table:

    if not rows:
        return pa.table(
            {name: pa.array([], type=t) for name, t in zip(schema.names, schema.types, strict=True)},
            schema=schema,
        )
    cols: dict[str, list[Any]] = {name: [] for name in schema.names}
    for r in rows:
        for name in schema.names:
            cols[name].append(r.get(name))
    arrays = {name: pa.array(cols[name], type=schema.field(name).type) for name in schema.names}
    return pa.table(arrays, schema=schema)





def read_parquet(path: str) -> pa.Table:
    return pq.read_table(path)


def write_parquet(table: pa.Table, dest: str) -> None:
    pq.write_table(table, dest, compression="snappy")
