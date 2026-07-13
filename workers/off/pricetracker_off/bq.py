#BigQuery access helpers

from __future__ import annotations

import uuid
from collections.abc import Iterable

from google.cloud import bigquery

from .logging import get_logger
from .off_client import OFFProduct

logger = get_logger(__name__)


def _client(project: str, location: str = "EU") -> bigquery.Client:
    return bigquery.Client(project=project, location=location)


def discover_eans_to_enrich(
    *,
    project_id: str,
    dataset: str,
    table_open_prices: str,
    table_catalogue: str,
    limit: int,
    location: str = "EU",
) -> list[str]:
    """Return up to `limit` EANs to enrich."""
    client = _client(project_id, location)
    sql = f"""
    SELECT op.product_code AS ean
    FROM `{project_id}.{dataset}.{table_open_prices}` op
    LEFT JOIN `{project_id}.{dataset}.{table_catalogue}` c
      ON c.ean = op.product_code
    WHERE op.product_code IS NOT NULL
      AND LENGTH(op.product_code) >= 8
      AND c.ean IS NULL
    GROUP BY ean
    ORDER BY ean
    LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)]
    )
    rows = client.query(sql, job_config=job_config).result()
    eans = [r["ean"] for r in rows]
    logger.info("bq_discover_done", count=len(eans), limit=limit)
    return eans


def fetch_median_prices(
    *,
    project_id: str,
    dataset: str,
    table_open_prices: str,
    window_weeks: int,
    min_obs: int,
    location: str = "EU",
) -> dict[str, tuple[float, int]]:
    #Médian de prix par EAN sur une fenêtre glissante
    client = _client(project_id, location)
    src = f"`{project_id}.{dataset}.{table_open_prices}`"
    sql = f"""
    SELECT
      product_code AS ean,
      APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_eur,
      COUNT(*) AS obs
    FROM {src}
    WHERE product_code IS NOT NULL
      AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
      AND price_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @window_weeks WEEK)
    GROUP BY product_code
    HAVING COUNT(*) >= @min_obs
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("window_weeks", "INT64", window_weeks),
            bigquery.ScalarQueryParameter("min_obs", "INT64", min_obs),
        ]
    )
    rows = client.query(sql, job_config=job_config).result()
    prices: dict[str, tuple[float, int]] = {}
    for r in rows:
        if r["median_eur"] is not None:
            prices[r["ean"]] = (float(r["median_eur"]), int(r["obs"]))
    logger.info("bq_median_prices_done", eans=len(prices), window_weeks=window_weeks)
    return prices


def merge_catalogue(
    *,
    project_id: str,
    dataset: str,
    table: str,
    products: Iterable[OFFProduct],
    enriched_at_iso: str,
    source: str = "openfoodfacts",
    location: str = "EU",
) -> int:
    #Load rows into staging then merge into the catalogue
    rows = [
        {
            "ean": p.ean,
            "name": p.name,
            "brand": p.brand,
            "category_l1": p.category_l1,
            "category_l2": p.category_l2,
            "category_l3": p.category_l3,
            "nutriscore": p.nutriscore,
            "nova": p.nova,
            "ecoscore": p.ecoscore,
            "image_url": p.image_url,
            "off_found": p.found,
            "enriched_at": enriched_at_iso,
            "source": source,
        }
        for p in products
    ]
    if not rows:
        logger.info("bq_merge_skipped", reason="no_rows")
        return 0

    client = _client(project_id, location)
    target = f"{project_id}.{dataset}.{table}"
    staging = f"{project_id}.{dataset}._stg_{table}_{uuid.uuid4().hex[:12]}"

    # Schéma explicite : asyncpg ne sera pas dans la chaîne mais BQ a besoin
    # du schéma pour le type checking, surtout `BOOL` et `TIMESTAMP`.
    schema = [
        bigquery.SchemaField("ean", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("brand", "STRING"),
        bigquery.SchemaField("category_l1", "STRING"),
        bigquery.SchemaField("category_l2", "STRING"),
        bigquery.SchemaField("category_l3", "STRING"),
        bigquery.SchemaField("nutriscore", "STRING"),
        bigquery.SchemaField("nova", "STRING"),
        bigquery.SchemaField("ecoscore", "STRING"),
        bigquery.SchemaField("image_url", "STRING"),
        bigquery.SchemaField("off_found", "BOOL", mode="REQUIRED"),
        bigquery.SchemaField("enriched_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("source", "STRING", mode="REQUIRED"),
    ]
    load_job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        schema=schema,
    )
    logger.info("bq_load_start", staging=staging, rows=len(rows))
    load_job = client.load_table_from_json(rows, staging, job_config=load_job_config)
    load_job.result()
    logger.info("bq_load_done", staging=staging)

    merge_sql = f"""
    MERGE `{target}` T
    USING `{staging}` S
    ON T.ean = S.ean
    WHEN MATCHED THEN
      UPDATE SET
        name = S.name,
        brand = S.brand,
        category_l1 = S.category_l1,
        category_l2 = S.category_l2,
        category_l3 = S.category_l3,
        nutriscore = S.nutriscore,
        nova = S.nova,
        ecoscore = S.ecoscore,
        image_url = S.image_url,
        off_found = S.off_found,
        enriched_at = S.enriched_at,
        source = S.source
    WHEN NOT MATCHED THEN
      INSERT (ean, name, brand, category_l1, category_l2, category_l3,
              nutriscore, nova, ecoscore, image_url, off_found, enriched_at, source)
      VALUES (S.ean, S.name, S.brand, S.category_l1, S.category_l2, S.category_l3,
              S.nutriscore, S.nova, S.ecoscore, S.image_url, S.off_found, S.enriched_at, S.source)
    """
    merge_job = client.query(merge_sql)
    merge_job.result()
    affected = merge_job.num_dml_affected_rows or 0
    logger.info("bq_merge_done", target=target, affected=affected)

    client.delete_table(staging, not_found_ok=True)
    return affected
