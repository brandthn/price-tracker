"""Router indices — perso, national, régional.

Schémas RÉELS des tables (cf. workers/indices/pricetracker_indices/bq.py) :
- Gold `indices_inflation` : (week_start_date, store_brand_normalized,
  country_code, observations, median_price_eur, base_price, index_value).
  Une série base-100 PAR enseigne — pas de scope national pré-calculé.
- Silver `open_prices_clean` : prix unitaires géolocalisés (postcode) —
  seule source pour la dimension départementale.

L'indice national est donc dérivé ici : moyenne des `index_value` par
enseigne pondérée par `observations`, semaine par semaine. L'indice
régional est recalculé depuis Silver (médiane hebdo du département,
base 100 sur la première semaine de la fenêtre).

Tant que les tables sont vides, on renvoie `series=[]` avec `current=None`
plutôt que de planter — contrat utile pour le frontend (état "en
construction").
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from google.cloud import bigquery

from .. import bq
from ..auth import AuthenticatedUser, verify_bearer
from ..config import get_settings
from ..schemas.indices import IndexPoint, InflationIndexOut

router = APIRouter(prefix="/indices", tags=["indices"])

_INDICES_TABLE = "indices_inflation"
_SILVER_PRICES_TABLE = "open_prices_clean"

# Fenêtre régionale ancrée sur MAX(week_start_date) (et pas CURRENT_DATE) :
# robuste si l'ingestion a du retard — la série reste affichable.
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
async def get_national() -> InflationIndexOut:
    settings = get_settings()
    sql = f"""
    SELECT
      week_start_date AS date,
      SAFE_DIVIDE(SUM(index_value * observations), SUM(observations)) AS value,
      SUM(observations) AS sample_size,
      CAST(MIN(week_start_date) OVER () AS STRING) AS base_period
    FROM {bq.qualified(settings.prt_bq_dataset_gold, _INDICES_TABLE)}
    WHERE country_code = 'FR' AND index_value IS NOT NULL
    GROUP BY week_start_date
    ORDER BY week_start_date
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
    """Indice personnel : non matérialisé à ce jour (le worker indices ne
    calcule pas de scope 'personal'). On garde le contrat — `series=[]` —
    et le frontend s'appuie sur `/me/basket` (Cloud SQL) pour la vue
    « Mon budget ». À réévaluer quand le worker matérialisera l'indice.
    """
    del user  # auth requise, pas de donnée à ce jour
    return _build_index("personal", [])
