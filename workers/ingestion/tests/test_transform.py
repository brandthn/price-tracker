"""Vérifie la normalisation parquet brut → schéma SILVER.

On construit le parquet d'entrée à la volée (pas de fixture binaire à
versionner) pour rester explicite sur le schéma et résilient si pyarrow
évolue.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pyarrow as pa

from src.transform import SILVER_SCHEMA, normalize


def _build_raw_table() -> pa.Table:
    return pa.table(
        {
            "id": ["1", "2", "3", "3", "4"],
            "date": [date(2026, 5, 17)] * 5,
            "code": ["3017620422003", "8076809513753", None, None, "1234567890"],
            "product_name": ["Nutella", "Pasta", "Eggs", "Eggs", "Soup"],
            "price": [3.49, 1.20, 4.10, 4.10, 2.50],
            "currency": ["EUR", "EUR", "EUR", "EUR", "USD"],
            "location_id": [1, 1, 2, 2, 99],
            "location_osm_name": ["Lidl Paris", "Lidl Paris", "Carrefour", "Carrefour", "Walmart"],
            "location_osm_address_country_code": ["FR", "FR", "FR", "FR", "US"],
            "category_tag": [None, None, "fr:oeufs", "fr:oeufs", None],
            "kind": ["product", "product", "product", "product", "product"],
        }
    )


def test_normalize_filters_country_and_dedupes() -> None:
    raw = _build_raw_table()
    out = normalize(raw, country_code_filter="FR")

    # Schéma exact attendu
    assert out.schema == SILVER_SCHEMA
    # 5 lignes brutes → -1 US (filtré) → -1 doublon `id=3` → 3 lignes
    assert out.num_rows == 3
    ids = sorted(out.column("id").to_pylist())
    assert ids == ["1", "2", "3"]
    # `kind` uppercase
    assert all(k == "PRODUCT" for k in out.column("kind").to_pylist())
    # `source` constant
    assert set(out.column("source").to_pylist()) == {"hf-open-prices"}


def test_normalize_no_country_filter_keeps_all() -> None:
    raw = _build_raw_table()
    out = normalize(raw, country_code_filter=None)
    # Dédup uniquement → 4 lignes
    assert out.num_rows == 4


def test_normalize_uses_provided_ingested_at() -> None:
    raw = _build_raw_table()
    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    out = normalize(raw, country_code_filter=None, ingested_at=ts)
    ingested = out.column("ingested_at").to_pylist()
    assert all(v == ts for v in ingested)


def test_normalize_kind_defaults_to_product_when_missing() -> None:
    raw = pa.table(
        {
            "id": ["a"],
            "date": [date(2026, 5, 17)],
            "code": ["1"],
            "product_name": ["X"],
            "price": [1.0],
            "currency": ["EUR"],
            "location_id": [1],
            "location_osm_name": ["x"],
            "location_osm_address_country_code": ["FR"],
            "category_tag": [None],
            # pas de colonne `kind`
        }
    )
    out = normalize(raw, country_code_filter="FR")
    assert out.column("kind").to_pylist() == ["PRODUCT"]
