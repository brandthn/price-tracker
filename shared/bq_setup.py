"""Création idempotente du dataset et des tables Silver de base."""

from __future__ import annotations

import os

from google.cloud import bigquery
from google.api_core import exceptions as gexc

from shared.bq_schema import (
    CATALOGUE_PRODUITS_SCHEMA,
    OPENPRICES_CLEAN_SCHEMA,
    OPENPRICES_REJECTIONS_SCHEMA,
)


def ensure_dataset_and_silver_tables(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    location: str | None = None,
) -> None:
    """Crée le dataset (si besoin) et les tables Silver référencées par les workers."""
    loc = location or os.getenv("BQ_LOCATION", "EU")
    dataset_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")
    dataset_ref.location = loc
    client.create_dataset(dataset_ref, exists_ok=True)

    _ensure_table(
        client,
        project_id,
        dataset_id,
        "openpricesclean",
        OPENPRICES_CLEAN_SCHEMA,
        partition_field="price_date",
    )
    _ensure_table(
        client,
        project_id,
        dataset_id,
        "openpricesrejections",
        OPENPRICES_REJECTIONS_SCHEMA,
        partition_field="pipeline_run_date",
    )
    _ensure_table(
        client,
        project_id,
        dataset_id,
        "catalogueproduits",
        CATALOGUE_PRODUITS_SCHEMA,
        partition_field=None,
        cluster_fields=["ean"],
    )


def _ensure_table(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    table_name: str,
    schema: list,
    partition_field: str | None,
    cluster_fields: list | None = None,
) -> None:
    table_ref = f"{project_id}.{dataset_id}.{table_name}"
    try:
        client.get_table(table_ref)
        return
    except gexc.NotFound:
        pass

    table = bigquery.Table(table_ref, schema=schema)
    if partition_field:
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=partition_field,
        )
    if cluster_fields:
        table.clustering_fields = cluster_fields
    client.create_table(table)
