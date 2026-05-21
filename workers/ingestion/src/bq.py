"""Load BigQuery Silver `open_prices_clean` en deux étapes : staging + MERGE.

Pourquoi pas un load direct avec `WRITE_TRUNCATE` ?
- La table est partitionnée par `date`, mais le snapshot HF contient
  plusieurs jours → on ne peut pas tronquer en sécurité.
- Le snapshot est cumulatif (Open Prices ne supprime jamais d'enregistrement),
  donc un MERGE sur `id` garde la table cohérente et idempotente.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from google.cloud import bigquery

from .logging import get_logger

logger = get_logger(__name__)


def _staging_table_id(project: str, dataset: str, target_table: str) -> str:
    run_id = uuid.uuid4().hex[:12]
    return f"{project}.{dataset}._stg_{target_table}_{run_id}"


def load_and_merge(
    *,
    project_id: str,
    location: str,
    dataset: str,
    table: str,
    gcs_uri: str,
) -> int:
    """Charge `gcs_uri` (parquet) dans une staging table, MERGE sur `id` vers la
    table cible, drop staging. Retourne le nombre de lignes affectées par le MERGE.
    """
    client = bigquery.Client(project=project_id, location=location)
    target_full = f"{project_id}.{dataset}.{table}"
    staging_full = _staging_table_id(project_id, dataset, table)

    load_job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
    )
    logger.info("bq_load_start", staging=staging_full, source=gcs_uri)
    load_job = client.load_table_from_uri(
        source_uris=[gcs_uri],
        destination=staging_full,
        job_config=load_job_config,
    )
    load_job.result()  # raise si échec
    staging_rows = client.get_table(staging_full).num_rows
    logger.info("bq_load_done", staging=staging_full, rows=staging_rows)

    merge_sql = f"""
    MERGE `{target_full}` T
    USING `{staging_full}` S
    ON T.id = S.id
    WHEN MATCHED THEN
      UPDATE SET
        date = S.date,
        product_code = S.product_code,
        product_name = S.product_name,
        price = S.price,
        currency = S.currency,
        location_id = S.location_id,
        location_osm_name = S.location_osm_name,
        country_code = S.country_code,
        category_tag = S.category_tag,
        kind = S.kind,
        source = S.source,
        ingested_at = S.ingested_at
    WHEN NOT MATCHED THEN
      INSERT (id, date, product_code, product_name, price, currency,
              location_id, location_osm_name, country_code, category_tag,
              kind, source, ingested_at)
      VALUES (S.id, S.date, S.product_code, S.product_name, S.price, S.currency,
              S.location_id, S.location_osm_name, S.country_code, S.category_tag,
              S.kind, S.source, S.ingested_at)
    """
    logger.info("bq_merge_start", target=target_full)
    merge_job = client.query(merge_sql)
    merge_job.result()
    affected = merge_job.num_dml_affected_rows or 0
    logger.info("bq_merge_done", target=target_full, affected=affected)

    client.delete_table(staging_full, not_found_ok=True)
    logger.info("bq_staging_dropped", staging=staging_full)
    return affected


def utcnow() -> datetime:
    return datetime.now(UTC)
