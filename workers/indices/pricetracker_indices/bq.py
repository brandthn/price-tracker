"""BigQuery SQL — recalcul Gold (4 tables) à partir de Silver.

Stratégie d'écriture : `TRUNCATE TABLE` + `INSERT INTO ... SELECT ...`. Préserve
la partition / clustering / labels gérés par Terraform, contrairement à
`CREATE OR REPLACE TABLE` qui les recréerait sans ces options.

Filtre IQR : on exclut les outliers déjà flaggés par le cleaner ingestion
(`iqr_outlier = TRUE`) avant de calculer les médianes — évite que les valeurs
extrêmes ne biaisent les agrégats Gold.

Fenêtre glissante : 12 semaines pour les agrégats/indices (suffisant pour voir
les tendances saisonnières court terme), 8 semaines pour les rankings/anomalies
(focus sur les variations récentes signalables aux utilisateurs).
"""

from __future__ import annotations

from dataclasses import dataclass

from google.cloud import bigquery

from .logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class IndicesConfig:
    project_id: str
    dataset_silver: str
    dataset_gold: str
    table_open_prices: str
    table_aggregats: str
    table_indices: str
    table_rankings: str
    table_anomalies: str
    location: str
    min_observations: int
    window_weeks_aggregats: int
    window_weeks_rankings: int
    z_threshold: float
    top_n_rankings: int


def _client(project: str, location: str) -> bigquery.Client:
    return bigquery.Client(project=project, location=location)


def _fq(project: str, dataset: str, table: str) -> str:
    return f"`{project}.{dataset}.{table}`"


def _params(cfg: IndicesConfig, run_date: str) -> list[bigquery.ScalarQueryParameter]:
    return [
        bigquery.ScalarQueryParameter("run_date", "DATE", run_date),
        bigquery.ScalarQueryParameter("min_obs", "INT64", cfg.min_observations),
        bigquery.ScalarQueryParameter("window_weeks_agg", "INT64", cfg.window_weeks_aggregats),
        bigquery.ScalarQueryParameter("window_weeks_rk", "INT64", cfg.window_weeks_rankings),
        bigquery.ScalarQueryParameter("z_threshold", "FLOAT64", cfg.z_threshold),
        bigquery.ScalarQueryParameter("top_n", "INT64", cfg.top_n_rankings),
    ]


def _sql_aggregats(cfg: IndicesConfig) -> str:
    src = _fq(cfg.project_id, cfg.dataset_silver, cfg.table_open_prices)
    dst = _fq(cfg.project_id, cfg.dataset_gold, cfg.table_aggregats)
    return f"""
    TRUNCATE TABLE {dst};
    INSERT INTO {dst}
      (week_start_date, store_brand_normalized, country_code, observations, avg_price_eur, median_price_eur)
    SELECT
      week_start_date,
      store_brand_normalized,
      country_code,
      COUNT(*) AS observations,
      AVG(price_eur) AS avg_price_eur,
      APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur
    FROM {src}
    WHERE week_start_date >= DATE_SUB(@run_date, INTERVAL @window_weeks_agg WEEK)
      AND store_brand_normalized IS NOT NULL
      AND country_code IS NOT NULL
      AND week_start_date IS NOT NULL
      AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
    GROUP BY week_start_date, store_brand_normalized, country_code
    HAVING COUNT(*) >= @min_obs;
    """


def _sql_indices(cfg: IndicesConfig) -> str:
    src = _fq(cfg.project_id, cfg.dataset_silver, cfg.table_open_prices)
    dst = _fq(cfg.project_id, cfg.dataset_gold, cfg.table_indices)
    return f"""
    TRUNCATE TABLE {dst};
    INSERT INTO {dst}
      (week_start_date, store_brand_normalized, country_code, observations, median_price_eur, base_price, index_value)
    WITH med AS (
      SELECT
        week_start_date,
        store_brand_normalized,
        country_code,
        APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur,
        COUNT(*) AS observations
      FROM {src}
      WHERE week_start_date >= DATE_SUB(@run_date, INTERVAL @window_weeks_agg WEEK)
        AND store_brand_normalized IS NOT NULL
        AND country_code IS NOT NULL
        AND week_start_date IS NOT NULL
        AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
      GROUP BY week_start_date, store_brand_normalized, country_code
      HAVING COUNT(*) >= @min_obs
    ),
    bases AS (
      SELECT
        store_brand_normalized,
        country_code,
        median_price_eur AS base_price
      FROM med
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY store_brand_normalized, country_code
        ORDER BY week_start_date
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
    JOIN bases b USING (store_brand_normalized, country_code);
    """


def _sql_rankings(cfg: IndicesConfig) -> str:
    src = _fq(cfg.project_id, cfg.dataset_silver, cfg.table_open_prices)
    dst = _fq(cfg.project_id, cfg.dataset_gold, cfg.table_rankings)
    return f"""
    TRUNCATE TABLE {dst};
    INSERT INTO {dst}
      (reference_week, product_code, prev_median, curr_median, pct_change)
    WITH weekly AS (
      SELECT
        week_start_date,
        product_code,
        APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur,
        COUNT(*) AS observations
      FROM {src}
      WHERE week_start_date >= DATE_SUB(@run_date, INTERVAL @window_weeks_rk WEEK)
        AND product_code IS NOT NULL
        AND week_start_date IS NOT NULL
        AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
      GROUP BY week_start_date, product_code
      HAVING COUNT(*) >= @min_obs
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
    ) <= @top_n;
    """


def _sql_anomalies(cfg: IndicesConfig) -> str:
    src = _fq(cfg.project_id, cfg.dataset_silver, cfg.table_open_prices)
    dst = _fq(cfg.project_id, cfg.dataset_gold, cfg.table_anomalies)
    return f"""
    TRUNCATE TABLE {dst};
    INSERT INTO {dst}
      (week_start_date, product_code, store_brand_normalized, median_price_eur, observations, mean_med, std_med, z_score)
    WITH weekly AS (
      SELECT
        week_start_date,
        product_code,
        store_brand_normalized,
        APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur,
        COUNT(*) AS observations
      FROM {src}
      WHERE week_start_date >= DATE_SUB(@run_date, INTERVAL @window_weeks_rk WEEK)
        AND product_code IS NOT NULL
        AND store_brand_normalized IS NOT NULL
        AND week_start_date IS NOT NULL
        AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
      GROUP BY week_start_date, product_code, store_brand_normalized
      HAVING COUNT(*) >= @min_obs
    ),
    stats AS (
      SELECT
        week_start_date,
        product_code,
        store_brand_normalized,
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
      AND ABS(SAFE_DIVIDE(median_price_eur - mean_med, NULLIF(std_med, 0))) >= @z_threshold;
    """


def build_sql_plan(cfg: IndicesConfig) -> list[tuple[str, str]]:
    """Renvoie la liste ordonnée [(label, sql)] des 4 jobs Gold."""
    return [
        ("aggregats_enseignes", _sql_aggregats(cfg)),
        ("indices_inflation", _sql_indices(cfg)),
        ("rankings_produits", _sql_rankings(cfg)),
        ("anomalies_detected", _sql_anomalies(cfg)),
    ]


def _count_rows(client: bigquery.Client, project: str, dataset: str, table: str) -> int:
    sql = f"SELECT COUNT(*) AS n FROM {_fq(project, dataset, table)}"
    row = next(iter(client.query(sql).result()))
    return int(row["n"])


def refresh_gold_tables(cfg: IndicesConfig, run_date: str) -> dict[str, int]:
    """Exécute les 4 SQL (TRUNCATE + INSERT) puis renvoie le nombre de lignes
    publiées dans chaque table Gold."""
    client = _client(cfg.project_id, cfg.location)
    plan = build_sql_plan(cfg)
    job_config = bigquery.QueryJobConfig(query_parameters=_params(cfg, run_date))

    counts: dict[str, int] = {}
    for label, sql in plan:
        logger.info("bq_query_start", table=label, run_date=run_date)
        client.query(sql, job_config=job_config).result()
        # `TRUNCATE TABLE ...; INSERT INTO ...;` en script BQ exécute les deux
        # statements ; on relit le COUNT(*) pour avoir la métrique post-INSERT.
        table_name = {
            "aggregats_enseignes": cfg.table_aggregats,
            "indices_inflation": cfg.table_indices,
            "rankings_produits": cfg.table_rankings,
            "anomalies_detected": cfg.table_anomalies,
        }[label]
        counts[label] = _count_rows(client, cfg.project_id, cfg.dataset_gold, table_name)
        logger.info("bq_query_done", table=label, rows=counts[label])

    return counts
