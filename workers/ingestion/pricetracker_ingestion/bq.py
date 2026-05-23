"""Chargement BigQuery : MERGE clean + WRITE_TRUNCATE partition rejections.

Stratégie clean (`open_prices_clean`) :
    1. Load parquet GCS dans une staging table éphémère (WRITE_TRUNCATE).
    2. MERGE sur `id` vers la table finale partitionnée.
    3. DROP staging.
    Idempotent : un re-run du même snapshot produit 0 nouvelle ligne (les rows
    matchent toutes par `id`).

Stratégie rejections (`open_prices_rejections`) :
    Load parquet local (pyarrow → fichier temp) directement vers la **décoration
    partition** `table$YYYYMMDD` avec `WRITE_TRUNCATE`. Atomique côté BQ :
    la partition du jour est remplacée intégralement par le résultat du run.
    Idempotent : un re-run du jour J remplace la partition J.

    Pourquoi pas un MERGE comme pour clean ? La PK `id` peut être NULL en
    rejections (rejet avant tout parsing), donc MERGE serait ambigu. La
    partition decorator est plus simple et logiquement plus juste : "voici
    tous les rejets du run du jour".
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq
from google.cloud import bigquery

from .logging import get_logger

logger = get_logger(__name__)

# Liste des colonnes MERGE pour open_prices_clean — gardée explicite (et pas
# générée depuis le schéma) pour qu'un drift accidentel soit visible en code review.
_OPEN_PRICES_CLEAN_COLUMNS = (
    "id",
    "pipeline_run_date",
    "price_date",
    "week_start_date",
    "product_code",
    "price_eur",
    "price_eur_decimal",
    "price_without_discount_eur",
    "price_is_discounted",
    "currency",
    "proof_type",
    "country_code",
    "store_brand",
    "store_brand_normalized",
    "location_id",
    "location_name",
    "location_osm_display_name",
    "city",
    "postcode",
    "latitude",
    "longitude",
    "iqr_outlier",
    "source",
    "ingested_at",
    "raw_payload",
)


def _staging_table_id(project: str, dataset: str, target_table: str) -> str:
    run_id = uuid.uuid4().hex[:12]
    return f"{project}.{dataset}._stg_{target_table}_{run_id}"


def load_and_merge_clean(
    *,
    project_id: str,
    location: str,
    dataset: str,
    table: str,
    gcs_uri: str,
) -> int:
    """Charge `gcs_uri` (parquet) en staging, MERGE sur `id` vers la table cible.

    Retourne le nombre de lignes affectées par le MERGE (insert + update).
    """
    client = bigquery.Client(project=project_id, location=location)
    target_full = f"{project_id}.{dataset}.{table}"
    staging_full = _staging_table_id(project_id, dataset, table)

    load_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
    )
    logger.info("bq_clean_load_start", staging=staging_full, source=gcs_uri)
    client.load_table_from_uri(
        source_uris=[gcs_uri],
        destination=staging_full,
        job_config=load_config,
    ).result()
    staging_rows = client.get_table(staging_full).num_rows
    logger.info("bq_clean_load_done", staging=staging_full, rows=staging_rows)

    set_clause = ",\n        ".join(
        f"{col} = S.{col}" for col in _OPEN_PRICES_CLEAN_COLUMNS if col != "id"
    )
    insert_cols = ", ".join(_OPEN_PRICES_CLEAN_COLUMNS)
    insert_vals = ", ".join(f"S.{c}" for c in _OPEN_PRICES_CLEAN_COLUMNS)
    merge_sql = f"""
    MERGE `{target_full}` T
    USING `{staging_full}` S
    ON T.id = S.id
    WHEN MATCHED THEN UPDATE SET
        {set_clause}
    WHEN NOT MATCHED THEN
      INSERT ({insert_cols})
      VALUES ({insert_vals})
    """
    logger.info("bq_clean_merge_start", target=target_full)
    merge_job = client.query(merge_sql)
    merge_job.result()
    affected = merge_job.num_dml_affected_rows or 0
    logger.info("bq_clean_merge_done", target=target_full, affected=affected)

    client.delete_table(staging_full, not_found_ok=True)
    return affected


def load_rejections(
    *,
    project_id: str,
    location: str,
    dataset: str,
    table: str,
    rejections: pa.Table,
    partition_day: date,
) -> int:
    """Écrit `rejections` dans la partition `partition_day` (WRITE_TRUNCATE).

    Si `rejections` est vide, on TRUNCATE quand même la partition pour
    refléter le fait que le run du jour n'a rien rejeté (sinon une exécution
    précédente du même jour laisserait des résidus).
    """
    client = bigquery.Client(project=project_id, location=location)
    partition_suffix = partition_day.strftime("%Y%m%d")
    target_partition = f"{project_id}.{dataset}.{table}${partition_suffix}"

    load_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        # Pas CREATE_IF_NEEDED : la table doit déjà exister (créée par Terraform).
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
    )

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=True) as tmp:
        pq.write_table(rejections, tmp.name, compression="snappy")
        tmp.seek(0)
        logger.info(
            "bq_rejections_load_start",
            target=target_partition,
            rows=rejections.num_rows,
        )
        with open(tmp.name, "rb") as fh:
            client.load_table_from_file(
                fh,
                destination=target_partition,
                job_config=load_config,
            ).result()

    logger.info("bq_rejections_load_done", target=target_partition, rows=rejections.num_rows)
    return rejections.num_rows
