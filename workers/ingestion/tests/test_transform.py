"""Pipeline transform v2 : raw HF → (clean, rejections, metrics).

Construit le parquet d'entrée à la volée (pas de fixture binaire versionnée)
pour rester explicite sur le schéma et résilient si pyarrow évolue.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pyarrow as pa

from pricetracker_ingestion.cleaner import CleanerConfig
from pricetracker_ingestion.transform import (
    REJECTIONS_SCHEMA,
    SILVER_SCHEMA,
    transform_open_prices,
)


# Valides EAN-13 (checksum vérifié) — utilisés dans le bucket clean.
NUTELLA = "3017620422003"
PASTA = "8076809513753"


def _build_raw_table() -> pa.Table:
    """Snapshot HF synthétique avec un mix de cas (clean / rejets variés)."""
    return pa.table(
        {
            "id": ["1", "2", "3", "3", "4", "5", "6", "7", "8"],
            # HF expose `date`, hf_mapping le renomme en `price_date`.
            "date": [date(2026, 5, 17)] * 9,
            "product_code": [
                NUTELLA,
                PASTA,
                NUTELLA,
                NUTELLA,  # doublon `id=3`
                "9999999999999",  # checksum EAN invalide
                NUTELLA,
                NUTELLA,
                NUTELLA,
                NUTELLA,
            ],
            "price": [3.49, 1.20, 4.10, 4.10, 2.50, 0.005, 3.0, 3.50, 2.99],
            "currency": ["EUR", "EUR", "EUR", "EUR", "EUR", "EUR", "USD", "EUR", "EUR"],
            "location_id": ["1", "1", "2", "2", "1", "1", "1", "1", "1"],
            "location_osm_display_name": [
                "Lidl, 12 Rue de la Paix, Paris, France",
                "Lidl, 12 Rue de la Paix, Paris, France",
                "Carrefour Market, Lyon",
                "Carrefour Market, Lyon",
                "Auchan Hypermarché, Lille",
                "Lidl",
                "Walmart",
                "Carrefour Market, Lyon",
                "Carrefour Market, Lyon",
            ],
            # HF expose `location_osm_address_country` (nom), hf_mapping infère ISO2.
            "location_osm_address_country": ["France"] * 9,
            "location_osm_address_city": [
                "Paris",
                "Paris",
                "Lyon 7e Arrondissement",
                "Lyon 7e Arrondissement",
                "Lille",
                "Paris",
                "Paris",
                "LYON",
                "lyon",
            ],
            "proof_type": ["RECEIPT"] * 9,
            "price_is_discounted": [False] * 9,
        }
    )


def test_transform_schemas_match() -> None:
    raw = _build_raw_table()
    clean, rejected, _ = transform_open_prices(raw, pipeline_run_date=date(2026, 5, 17))
    assert clean.schema == SILVER_SCHEMA
    assert rejected.schema == REJECTIONS_SCHEMA


def test_transform_buckets_and_dedup() -> None:
    raw = _build_raw_table()
    clean, rejected, metrics = transform_open_prices(
        raw, pipeline_run_date=date(2026, 5, 17)
    )

    # 9 lignes → -1 doublon id=3 → -1 EAN invalide (id=4) → -1 prix < 0.01 EUR (id=5)
    # -1 currency=USD (id=6) → 5 clean.
    # 9 input - 5 clean - 1 dédup = 3 rejets (EAN, prix, devise).
    assert clean.num_rows == 5
    assert rejected.num_rows == 3
    assert metrics["rows_input"] == 9
    assert metrics["rows_clean"] == 5
    assert metrics["rows_rejected"] == 3


def test_transform_rejection_reasons() -> None:
    raw = _build_raw_table()
    _, rejected, metrics = transform_open_prices(
        raw, pipeline_run_date=date(2026, 5, 17)
    )
    reasons = sorted(rejected.column("reason").to_pylist())
    assert reasons == sorted(
        ["INVALID_EAN", "OUT_OF_RANGE_PRICE", "INVALID_CURRENCY"]
    )
    assert metrics["rejections_by_reason"]["INVALID_EAN"] == 1
    assert metrics["rejections_by_reason"]["OUT_OF_RANGE_PRICE"] == 1
    assert metrics["rejections_by_reason"]["INVALID_CURRENCY"] == 1


def test_transform_store_brand_normalized() -> None:
    raw = _build_raw_table()
    clean, _, _ = transform_open_prices(raw, pipeline_run_date=date(2026, 5, 17))
    brands = sorted(set(clean.column("store_brand_normalized").to_pylist()))
    # "Lidl, ..." → "Lidl" ; "Carrefour Market, ..." → "Carrefour Market"
    assert "Lidl" in brands
    assert "Carrefour Market" in brands


def test_transform_city_normalized() -> None:
    raw = _build_raw_table()
    clean, _, _ = transform_open_prices(raw, pipeline_run_date=date(2026, 5, 17))
    cities = sorted(set(clean.column("city").to_pylist()))
    # Vérifie : "Lyon 7e Arrondissement" → "Lyon", "LYON" → "Lyon", "lyon" → "Lyon"
    assert cities == ["Lyon", "Paris"]


def test_transform_injects_run_metadata() -> None:
    raw = _build_raw_table()
    run_dt = datetime(2026, 5, 17, 3, 0, 0, tzinfo=UTC)
    clean, rejected, _ = transform_open_prices(
        raw,
        pipeline_run_date=run_dt.date(),
        ingested_at=run_dt,
    )
    assert all(d == date(2026, 5, 17) for d in clean.column("pipeline_run_date").to_pylist())
    assert all(t == run_dt for t in clean.column("ingested_at").to_pylist())
    assert set(clean.column("source").to_pylist()) == {"hf-open-prices"}
    # Idem côté rejections : pipeline_run_date + rejected_at.
    assert all(d == date(2026, 5, 17) for d in rejected.column("pipeline_run_date").to_pylist())


def test_transform_week_start_date() -> None:
    raw = _build_raw_table()
    clean, _, _ = transform_open_prices(raw, pipeline_run_date=date(2026, 5, 17))
    # 2026-05-17 = dimanche → semaine ISO commence le lundi 2026-05-11.
    weeks = set(clean.column("week_start_date").to_pylist())
    assert weeks == {date(2026, 5, 11)}


def test_transform_empty_input() -> None:
    empty = pa.table({"id": pa.array([], type=pa.string())})
    clean, rejected, metrics = transform_open_prices(
        empty, pipeline_run_date=date(2026, 5, 17)
    )
    assert clean.num_rows == 0
    assert rejected.num_rows == 0
    assert clean.schema == SILVER_SCHEMA
    assert rejected.schema == REJECTIONS_SCHEMA
    assert metrics["rows_input"] == 0


def test_transform_raw_payload_preserved() -> None:
    """Le JSON brut de chaque ligne HF est sérialisé dans `raw_payload`."""
    raw = _build_raw_table()
    clean, rejected, _ = transform_open_prices(raw, pipeline_run_date=date(2026, 5, 17))
    payloads = clean.column("raw_payload").to_pylist()
    assert all(isinstance(p, str) and p.startswith("{") for p in payloads)
    rej_payloads = rejected.column("raw_payload").to_pylist()
    assert all(isinstance(p, str) and p.startswith("{") for p in rej_payloads)


def test_transform_country_filter_via_config() -> None:
    """Une CleanerConfig restreinte à FR rejette les lignes hors FR."""
    raw = pa.table(
        {
            "id": ["a", "b"],
            "date": [date(2026, 5, 17), date(2026, 5, 17)],
            "product_code": [NUTELLA, NUTELLA],
            "price": [3.49, 3.49],
            "currency": ["EUR", "EUR"],
            "location_osm_address_country": ["France", "Belgium"],
            "proof_type": ["RECEIPT", "RECEIPT"],
        }
    )
    config = CleanerConfig(
        allowed_countries=frozenset({"FR"}),
        reference_date=date(2026, 5, 17),
    )
    clean, rejected, _ = transform_open_prices(
        raw, pipeline_run_date=date(2026, 5, 17), config=config
    )
    assert clean.num_rows == 1
    assert rejected.num_rows == 1
    assert rejected.column("reason").to_pylist() == ["INVALID_COUNTRY"]
