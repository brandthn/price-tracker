"""Schémas BigQuery — Silver et Gold. Alignés sur schemas/bigquery/*.json."""

from __future__ import annotations

from google.cloud import bigquery

# ── Silver : prix nettoyés ────────────────────────────────────────────────────
OPENPRICES_CLEAN_SCHEMA = [
    bigquery.SchemaField("pipeline_run_date",          "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("id",                         "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("product_code",               "STRING"),
    bigquery.SchemaField("price_eur",                  "FLOAT64",   mode="REQUIRED"),
    bigquery.SchemaField("price_eur_decimal",          "STRING"),
    bigquery.SchemaField("price_without_discount_eur", "FLOAT64"),
    bigquery.SchemaField("price_is_discounted",        "BOOL"),
    bigquery.SchemaField("currency",                   "STRING"),
    bigquery.SchemaField("price_date",                 "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("week_start_date",            "DATE"),
    bigquery.SchemaField("proof_type",                 "STRING"),
    bigquery.SchemaField("country_code",               "STRING"),
    bigquery.SchemaField("store_brand",                "STRING"),
    bigquery.SchemaField("store_brand_normalized",     "STRING"),
    bigquery.SchemaField("location_id",                "STRING"),
    bigquery.SchemaField("location_name",              "STRING"),
    bigquery.SchemaField("location_osm_display_name",  "STRING"),
    bigquery.SchemaField("city",                       "STRING"),
    bigquery.SchemaField("postcode",                   "STRING"),
    bigquery.SchemaField("latitude",                   "FLOAT64"),
    bigquery.SchemaField("longitude",                  "FLOAT64"),
    bigquery.SchemaField("source",                     "STRING"),
    bigquery.SchemaField("ingested_at",                "TIMESTAMP"),
    bigquery.SchemaField("raw_payload",                "STRING"),
]

# ── Silver : rejets ───────────────────────────────────────────────────────────
OPENPRICES_REJECTIONS_SCHEMA = [
    bigquery.SchemaField("pipeline_run_date", "DATE",   mode="REQUIRED"),
    bigquery.SchemaField("id",                "STRING"),
    bigquery.SchemaField("product_code",      "STRING"),
    bigquery.SchemaField("reason",            "STRING", mode="REQUIRED"),
    bigquery.SchemaField("details",           "STRING"),
    bigquery.SchemaField("currency",          "STRING"),
    bigquery.SchemaField("raw_price",         "STRING"),
    bigquery.SchemaField("price_date",        "STRING"),
    bigquery.SchemaField("country_code",      "STRING"),
    bigquery.SchemaField("proof_type",        "STRING"),
    bigquery.SchemaField("rejected_at",       "STRING"),
    bigquery.SchemaField("raw_payload",       "STRING"),
]

# ── Silver : catalogue produits Open Food Facts ───────────────────────────────
# Schéma aligné sur schemas/bigquery/silver_catalogueproduits.json
CATALOGUE_PRODUITS_SCHEMA = [
    bigquery.SchemaField("ean",          "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("name",         "STRING"),
    bigquery.SchemaField("brand",        "STRING"),
    bigquery.SchemaField("category_l1",  "STRING"),
    bigquery.SchemaField("category_l2",  "STRING"),
    bigquery.SchemaField("category_l3",  "STRING"),
    bigquery.SchemaField("nutriscore",   "STRING"),
    bigquery.SchemaField("nova",         "STRING"),
    bigquery.SchemaField("ecoscore",     "STRING"),
    bigquery.SchemaField("image_url",    "STRING"),
    bigquery.SchemaField("off_found",    "BOOL",      mode="REQUIRED"),
    bigquery.SchemaField("enriched_at",  "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("source",       "STRING",    mode="REQUIRED"),
]
