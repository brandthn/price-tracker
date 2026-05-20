"""
Worker indices — couches Gold (guide §5 worker 3).

Recalcule (via BigQuery) :
  - `aggregatsenseignes` : volumes et prix médians par semaine / enseigne / pays ;
  - `indicesinflation` : indice chaîne simple (base 100) sur la médiane hebdomadaire ;
  - `rankingsproduits` : plus fortes hausses de prix médian entre deux semaines ;
  - `anomaliesdetected` : écarts à la médiane hebdomadaire par produit (score robuste).

Quality gate : si des indices sont publiés, la taille minimale de chaque groupe agrégé
doit respecter `MIN_OBSERVATIONS_FOR_INDEX` (contrôle post-SQL).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from loguru import logger

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from google.cloud import bigquery, storage  # noqa: E402

from shared.config import load_settings, utc_today_iso  # noqa: E402
from shared.monitoring import (  # noqa: E402
    STATUS_FAILED,
    STATUS_SUCCESS,
    QualityGateError,
    build_worker_signal,
    evaluate_min_threshold,
    raise_if_quality_gates_failed,
    utcnow_iso,
    write_signal_to_bucket,
)
from shared.orchestration import wait_for_upstream_worker  # noqa: E402
from shared.signals import write_local_signal  # noqa: E402


def _execution_date() -> str:
    return os.getenv("EXECUTION_DATE") or utc_today_iso()


def _persist_signal(settings, execution_date: str, payload: Dict[str, Any]) -> str:
    if settings.use_gcp and settings.gcs_signals_bucket:
        client = storage.Client(project=settings.project_id)
        return write_signal_to_bucket(
            storage_client=client,
            bucket_name=settings.gcs_signals_bucket,
            execution_date=execution_date,
            worker_name="worker_indices",
            signal_payload=payload,
        )
    path = write_local_signal(Path("./artifacts"), execution_date, "worker_indices", payload)
    return str(path)


def _gold_sql(project: str, dataset: str, run_date: str, min_obs: int) -> List[str]:
    fq = f"`{project}.{dataset}`"
    return [
        f"""
        CREATE OR REPLACE TABLE {fq}.aggregatsenseignes
        PARTITION BY week_start_date AS
        WITH base AS (
          SELECT
            c.week_start_date,
            c.store_brand_normalized,
            c.country_code,
            c.product_code,
            c.price_eur,
            cat.categories AS product_categories
          FROM {fq}.openpricesclean c
          LEFT JOIN {fq}.catalogueproduits cat USING (product_code)
          WHERE c.week_start_date >= DATE_SUB(DATE('{run_date}'), INTERVAL 12 WEEK)
        )
        SELECT
          week_start_date,
          store_brand_normalized,
          country_code,
          ANY_VALUE(product_categories) AS sample_categories,
          COUNT(*) AS observations,
          AVG(price_eur) AS avg_price_eur,
          APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur
        FROM base
        WHERE store_brand_normalized IS NOT NULL
        GROUP BY week_start_date, store_brand_normalized, country_code
        HAVING COUNT(*) >= {min_obs}
        """,
        f"""
        CREATE OR REPLACE TABLE {fq}.indicesinflation AS
        WITH med AS (
          SELECT
            week_start_date,
            store_brand_normalized,
            country_code,
            APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur,
            COUNT(*) AS observations
          FROM {fq}.openpricesclean
          WHERE week_start_date >= DATE_SUB(DATE('{run_date}'), INTERVAL 12 WEEK)
            AND store_brand_normalized IS NOT NULL
          GROUP BY week_start_date, store_brand_normalized, country_code
          HAVING COUNT(*) >= {min_obs}
        ),
        bases AS (
          SELECT
            store_brand_normalized,
            country_code,
            median_price_eur AS base_price
          FROM med
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY store_brand_normalized, country_code ORDER BY week_start_date
          ) = 1
        )
        SELECT
          m.week_start_date,
          m.store_brand_normalized,
          m.country_code,
          m.observations,
          m.median_price_eur,
          b.base_price,
          SAFE_DIVIDE(m.median_price_eur, NULLIF(b.base_price, 0)) * 100 AS index_value
        FROM med m
        JOIN bases b USING (store_brand_normalized, country_code)
        """,
        f"""
        CREATE OR REPLACE TABLE {fq}.rankingsproduits AS
        WITH weekly AS (
          SELECT
            week_start_date,
            product_code,
            APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur,
            COUNT(*) AS observations
          FROM {fq}.openpricesclean
          WHERE week_start_date >= DATE_SUB(DATE('{run_date}'), INTERVAL 8 WEEK)
            AND product_code IS NOT NULL
          GROUP BY week_start_date, product_code
          HAVING COUNT(*) >= {min_obs}
        ),
        lagged AS (
          SELECT
            week_start_date,
            product_code,
            median_price_eur,
            LAG(median_price_eur) OVER (
              PARTITION BY product_code ORDER BY week_start_date
            ) AS prev_median
          FROM weekly
        )
        SELECT
          week_start_date AS reference_week,
          product_code,
          prev_median,
          median_price_eur AS curr_median,
          SAFE_DIVIDE(median_price_eur - prev_median, NULLIF(prev_median, 0)) AS pct_change
        FROM lagged
        WHERE prev_median IS NOT NULL AND prev_median > 0
        QUALIFY ROW_NUMBER() OVER (
          ORDER BY SAFE_DIVIDE(median_price_eur - prev_median, NULLIF(prev_median, 0)) DESC
        ) <= 500
        """,
        f"""
        CREATE OR REPLACE TABLE {fq}.anomaliesdetected AS
        WITH weekly AS (
          SELECT
            week_start_date,
            product_code,
            store_brand_normalized,
            APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur,
            COUNT(*) AS observations
          FROM {fq}.openpricesclean
          WHERE week_start_date >= DATE_SUB(DATE('{run_date}'), INTERVAL 8 WEEK)
          GROUP BY week_start_date, product_code, store_brand_normalized
          HAVING COUNT(*) >= {min_obs}
        ),
        stats AS (
          SELECT
            product_code,
            store_brand_normalized,
            week_start_date,
            median_price_eur,
            observations,
            AVG(median_price_eur) OVER (PARTITION BY product_code, store_brand_normalized) AS mean_med,
            STDDEV_POP(median_price_eur) OVER (PARTITION BY product_code, store_brand_normalized) AS std_med
          FROM weekly
        )
        SELECT
          week_start_date,
          product_code,
          store_brand_normalized,
          median_price_eur,
          observations,
          mean_med,
          std_med,
          SAFE_DIVIDE(median_price_eur - mean_med, NULLIF(std_med, 0)) AS z_score
        FROM stats
        WHERE std_med IS NOT NULL AND std_med > 0
          AND ABS(SAFE_DIVIDE(median_price_eur - mean_med, NULLIF(std_med, 0))) >= 3
        """,
    ]


def _min_observations_in_indices(client: bigquery.Client, fq_table: str) -> tuple[int, int]:
    sql = f"""
    SELECT
      COUNT(*) AS n_rows,
      IFNULL(MIN(observations), 999999) AS min_obs
    FROM `{fq_table}.indicesinflation`
    """
    row = list(client.query(sql).result())[0]
    return int(row["n_rows"]), int(row["min_obs"])


def run() -> None:
    load_dotenv()
    settings = load_settings()
    execution_date = _execution_date()
    started_at = utcnow_iso()
    metrics: Dict[str, Any] = {}
    quality_gates: List[Dict[str, Any]] = []

    try:
        wait_for_upstream_worker(settings, execution_date, "worker_off")

        if not settings.use_gcp:
            logger.warning("worker_indices : GCP désactivé — pas de recalcul Gold.")
            finished_at = utcnow_iso()
            metrics = {"skipped": True, "reason": "GCP_PROJECT_ID non défini"}
            quality_gates = [
                evaluate_min_threshold(
                    "indices_min_group_observations",
                    float(settings.min_observations_for_index),
                    float(settings.min_observations_for_index),
                )
            ]
            payload = build_worker_signal(
                worker_name="worker_indices",
                execution_date=execution_date,
                status=STATUS_SUCCESS,
                started_at=started_at,
                finished_at=finished_at,
                metrics=metrics,
                quality_gates=quality_gates,
            )
            _persist_signal(settings, execution_date, payload)
            return

        client = bigquery.Client(project=settings.project_id)
        fq = f"{settings.project_id}.{settings.bq_dataset}"
        min_obs = settings.min_observations_for_index

        for stmt in _gold_sql(settings.project_id, settings.bq_dataset, execution_date, min_obs):
            client.query(stmt).result()

        n_rows, min_obs_seen = _min_observations_in_indices(client, fq)
        actual_gate = float(min_obs_seen) if n_rows > 0 else float(min_obs)
        quality_gates = [
            evaluate_min_threshold(
                "indices_min_group_observations",
                actual_gate,
                float(min_obs),
            )
        ]
        if n_rows > 0:
            raise_if_quality_gates_failed(quality_gates)

        metrics = {
            "indices_rows": n_rows,
            "min_observations_in_indices_table": min_obs_seen,
            "gold_tables_refreshed": [
                "aggregatsenseignes",
                "indicesinflation",
                "rankingsproduits",
                "anomaliesdetected",
            ],
        }

        finished_at = utcnow_iso()
        payload = build_worker_signal(
            worker_name="worker_indices",
            execution_date=execution_date,
            status=STATUS_SUCCESS,
            started_at=started_at,
            finished_at=finished_at,
            metrics=metrics,
            quality_gates=quality_gates,
        )
        dest = _persist_signal(settings, execution_date, payload)
        logger.success(f"worker_indices terminé — signal : {dest}")

    except Exception as exc:  # noqa: BLE001
        logger.exception("worker_indices en échec")
        finished_at = utcnow_iso()
        payload = build_worker_signal(
            worker_name="worker_indices",
            execution_date=execution_date,
            status=STATUS_FAILED,
            started_at=started_at,
            finished_at=finished_at,
            metrics=metrics,
            quality_gates=quality_gates,
            error_message=str(exc),
        )
        _persist_signal(settings, execution_date, payload)
        if isinstance(exc, QualityGateError):
            raise SystemExit(1) from exc
        raise SystemExit(1) from exc


def main() -> None:
    run()


if __name__ == "__main__":
    main()
