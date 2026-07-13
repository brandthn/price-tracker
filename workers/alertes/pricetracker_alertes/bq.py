

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.cloud import bigquery

from .logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AlertesConfig:
    project_id: str
    dataset_gold: str
    table_rankings: str
    table_anomalies: str
    location: str
    top_rankings: int
    top_anomalies: int
    min_pct_change: float
    lookback_weeks: int


def _client(project: str, location: str) -> bigquery.Client:
    return bigquery.Client(project=project, location=location)


def fetch_top_rankings(
    cfg: AlertesConfig, run_date: str
) -> list[dict[str, Any]]:

    client = _client(cfg.project_id, cfg.location)
    sql = f"""
    SELECT
      reference_week,
      product_code,
      prev_median,
      curr_median,
      pct_change
    FROM `{cfg.project_id}.{cfg.dataset_gold}.{cfg.table_rankings}`
    WHERE reference_week >= DATE_SUB(@run_date, INTERVAL @lookback WEEK)
      AND pct_change IS NOT NULL
      AND pct_change >= @min_pct
    ORDER BY pct_change DESC
    LIMIT @top_n
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run_date", "DATE", run_date),
            bigquery.ScalarQueryParameter("lookback", "INT64", cfg.lookback_weeks),
            bigquery.ScalarQueryParameter("min_pct", "FLOAT64", cfg.min_pct_change),
            bigquery.ScalarQueryParameter("top_n", "INT64", cfg.top_rankings),
        ]
    )
    rows = client.query(sql, job_config=job_config).result()
    return [_row_to_dict(row) for row in rows]


def fetch_top_anomalies(
    cfg: AlertesConfig, run_date: str
) -> list[dict[str, Any]]:

    client = _client(cfg.project_id, cfg.location)
    sql = f"""
    SELECT
      week_start_date,
      product_code,
      store_brand_normalized,
      median_price_eur,
      mean_med,
      std_med,
      z_score
    FROM `{cfg.project_id}.{cfg.dataset_gold}.{cfg.table_anomalies}`
    WHERE week_start_date >= DATE_SUB(@run_date, INTERVAL @lookback WEEK)
      AND z_score IS NOT NULL
    ORDER BY ABS(z_score) DESC
    LIMIT @top_n
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run_date", "DATE", run_date),
            bigquery.ScalarQueryParameter("lookback", "INT64", cfg.lookback_weeks),
            bigquery.ScalarQueryParameter("top_n", "INT64", cfg.top_anomalies),
        ]
    )
    rows = client.query(sql, job_config=job_config).result()
    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: bigquery.Row) -> dict[str, Any]:

    out: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            out[key] = None
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out
