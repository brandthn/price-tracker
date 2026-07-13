"""Router indices — perso, national, regional.

Schemas reels (workers/indices/.../bq.py) : Gold indices_inflation = serie
base-100 PAR enseigne (pas de national pre-calcule) ; Silver open_prices_clean =
prix geolocalises (postcode), seule source departementale.
National derive ici : moyenne des index_value ponderee par observations, par
semaine. Regional recalcule depuis Silver (mediane hebdo dept, base 100 sur la
1ere semaine). Tables vides -> series=[], current=None.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Query
from google.cloud import bigquery

from .. import bq
from ..auth import AuthenticatedUser, verify_bearer
from ..config import get_settings
from ..schemas.indices import IndexPoint, InflationIndexOut

router = APIRouter(prefix="/indices", tags=["indices"])

_INDICES_TABLE = "indices_inflation"
_SILVER_PRICES_TABLE = "open_prices_clean"

# fenetre ancree sur MAX(week_start_date), pas CURRENT_DATE : robuste au retard d'ingestion
_REGIONAL_WINDOW_WEEKS = 26
_REGIONAL_MIN_OBS = 3


def _build_index(scope: str, rows: list[dict]) -> InflationIndexOut:
    series = [
        IndexPoint(
            date=r["date"],
            value=float(r["value"]),
            sample_size=int(r["sample_size"]) if r.get("sample_size") is not None else None,
        )
        for r in rows
        if r.get("value") is not None
    ]
    current = series[-1].value if series else None
    base_period = rows[0].get("base_period") if rows else None
    return InflationIndexOut(
        scope=scope,
        base_period=base_period,
        current=current,
        series=series,
    )


@router.get("/national", response_model=InflationIndexOut)
async def get_national(
    granularity: Literal["week", "month"] = Query(default="week"),
) -> InflationIndexOut:
    settings = get_settings()
    # index_value deja base-100 par enseigne/semaine : agreger par mois reste une
    # moyenne ponderee base-100, pas de rebase
    period = (
        "week_start_date"
        if granularity == "week"
        else "DATE_TRUNC(week_start_date, MONTH)"
    )
    sql = f"""
    WITH agg AS (
      SELECT
        {period} AS date,
        SAFE_DIVIDE(SUM(index_value * observations), SUM(observations)) AS value,
        SUM(observations) AS sample_size
      FROM {bq.qualified(settings.prt_bq_dataset_gold, _INDICES_TABLE)}
      WHERE country_code = 'FR' AND index_value IS NOT NULL
      GROUP BY date
    )
    SELECT
      date,
      value,
      sample_size,
      CAST(MIN(date) OVER () AS STRING) AS base_period
    FROM agg
    ORDER BY date
    """
    rows = await asyncio.to_thread(bq.query_dicts_safe, sql, context="indices_national")
    return _build_index("national", rows)


@router.get("/regional/{departement}", response_model=InflationIndexOut)
async def get_regional(departement: str) -> InflationIndexOut:
    settings = get_settings()
    src = bq.qualified(settings.prt_bq_dataset_silver, _SILVER_PRICES_TABLE)
    sql = f"""
    WITH prices AS (
      SELECT week_start_date, price_eur
      FROM {src}
      WHERE country_code = 'FR'
        AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
        AND postcode IS NOT NULL
        AND week_start_date IS NOT NULL
        AND ({bq.DEPT_FROM_POSTCODE_SQL}) = @dept
        AND week_start_date >= DATE_SUB(
          (SELECT MAX(week_start_date) FROM {src}),
          INTERVAL {_REGIONAL_WINDOW_WEEKS} WEEK
        )
    ),
    weekly AS (
      SELECT
        week_start_date,
        APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price,
        COUNT(*) AS n
      FROM prices
      GROUP BY week_start_date
      HAVING COUNT(*) >= {_REGIONAL_MIN_OBS}
    )
    SELECT
      week_start_date AS date,
      SAFE_DIVIDE(median_price,
        FIRST_VALUE(median_price) OVER (ORDER BY week_start_date)) * 100 AS value,
      n AS sample_size,
      CAST(MIN(week_start_date) OVER () AS STRING) AS base_period
    FROM weekly
    ORDER BY week_start_date
    """
    rows = await asyncio.to_thread(
        bq.query_dicts_safe,
        sql,
        params=[bigquery.ScalarQueryParameter("dept", "STRING", departement.upper())],
        context=f"indices_regional_{departement}",
    )
    return _build_index(f"regional:{departement}", rows)


@router.get("/personal", response_model=InflationIndexOut)
async def get_personal(
    user: AuthenticatedUser = Depends(verify_bearer),
) -> InflationIndexOut:
    """Indice personnel : non materialise (le worker ne calcule pas ce scope).

    Contrat garde (series=[]) ; la vue budget passe par /me/basket (Cloud SQL).
    """
    del user  # auth requise, pas de donnee a ce jour
    return _build_index("personal", [])
