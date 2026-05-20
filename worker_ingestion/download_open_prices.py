"""Téléchargement du snapshot HuggingFace open-prices — France + DOM/TOM uniquement."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import duckdb
from datasets import load_dataset
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

COLUMNS_A_GARDER = [
    "id", "product_code", "price", "price_is_discounted",
    "price_without_discount", "currency", "date", "proof_type",
    "location_id", "location_osm_display_name",
    "location_osm_address_city", "location_osm_address_postcode",
    "location_osm_address_country", "location_osm_lat", "location_osm_lon",
    "source",
]

# Pays reconnus comme territoire français (comparaison lowercase)
_FRENCH_COUNTRY_NAMES = {
    "france", "guadeloupe", "martinique", "guyane",
    "réunion", "reunion", "mayotte", "saint-martin",
    "saint barthélemy", "saint-barthélemy",
    "saint pierre and miquelon", "wallis and futuna",
    "new caledonia", "nouvelle-calédonie",
    "french polynesia", "polynésie française",
}


def bronze_local_parquet_path(raw_base: str | None = None) -> Path:
    base = raw_base or os.getenv("RAW_DATA_PATH", "./raw")
    return Path(base) / "open_prices" / "open_prices.parquet"


def telecharger_open_prices(raw_base: str | None = None) -> Path:
    """Télécharge le split prices, filtre France + DOM/TOM, écrit le Parquet local."""
    output_file = bronze_local_parquet_path(raw_base)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Connexion à HuggingFace pour télécharger Open Prices...")
    dataset = load_dataset(
        "openfoodfacts/open-prices",
        split="prices",
        columns=COLUMNS_A_GARDER,
    )
    n_total = len(dataset)
    logger.info(f"Dataset reçu : {n_total:,} lignes (monde entier)")

    def _is_french(row: Dict[str, Any]) -> bool:
        country = row.get("location_osm_address_country") or ""
        return country.strip().lower() in _FRENCH_COUNTRY_NAMES

    logger.info("Pré-filtre France + DOM/TOM en cours...")
    dataset_fr = dataset.filter(_is_french, desc="Filtre France")
    n_fr = len(dataset_fr)
    pct = n_fr / n_total * 100 if n_total else 0
    logger.info(f"Lignes France conservées : {n_fr:,} ({pct:.1f}% du total mondial)")

    logger.info(f"Sauvegarde vers {output_file}...")
    dataset_fr.to_parquet(str(output_file))

    con = duckdb.connect()
    result = con.execute(
        f"SELECT COUNT(*) AS nb FROM read_parquet('{output_file}')"
    ).fetchone()
    con.close()

    logger.success(f"Parquet vérifié : {result[0]:,} lignes dans {output_file}")
    return output_file
