"""Router observatoire public — rankings, hall of shame, carte.

Schemas reels (workers/indices/.../bq.py) : Gold rankings_produits
(reference_week, product_code, prev/curr_median, pct_change RATIO ; hausses only,
sans nom) ; Silver open_prices_clean (prix unitaires postcode/enseigne/semaine).
Noms resolus contre Cloud SQL products (BQ renvoie EAN+prix, batch SQL complete
nom/marque/image) ; EAN hors catalogue -> in_catalog=false. Granularite week/month.
Tables vides -> 200 items=[], pas 500.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import bq
from ..config import get_settings
from ..db import get_session
from ..schemas.indices import (
    MapDepartementValue,
    MapOut,
    RankingItem,
    RankingsOut,
)
from ..services.catalog import resolve_products

router = APIRouter(prefix="/observatoire", tags=["observatoire"])

Granularity = Literal["week", "month"]

# Fenêtre de comparaison : plus large en mensuel pour garantir ≥ 2 buckets.
_RANKINGS_WINDOW_WEEKS = {"week": 8, "month": 16}
# Demi-fenêtre de la carte (récent vs précédent).
_MAP_HALF_WINDOW_WEEKS = {"week": 4, "month": 8}
_MIN_OBS = 3


def _period_expr(granularity: Granularity) -> str:
    # bucket temporel sur week_start_date
    return (
        "week_start_date"
        if granularity == "week"
        else "DATE_TRUNC(week_start_date, MONTH)"
    )


def _silver_fq() -> str:
    settings = get_settings()
    return bq.qualified(settings.prt_bq_dataset_silver, "open_prices_clean")


def _build_rankings(rows: list[dict], resolved: dict[str, dict]) -> list[RankingItem]:
    items: list[RankingItem] = []
    for r in rows:
        ean = r.get("ean")
        cat = resolved.get(ean) if ean else None
        items.append(
            RankingItem(
                ean=ean,
                produit_nom=(cat or {}).get("name"),
                brand=(cat or {}).get("brand"),
                image_url=(cat or {}).get("image_url"),
                in_catalog=cat is not None,
                pct_change=float(r["pct_change"]) if r.get("pct_change") is not None else 0.0,
                price_eur_current=r.get("price_eur_current"),
                price_eur_previous=r.get("price_eur_previous"),
                sample_size=r.get("sample_size"),
            )
        )
    return items


def _silver_changes_cte(granularity: Granularity) -> str:
    # CTE : derniere variation mediane par produit sur la fenetre, depuis Silver.
    # expose (product_code, pct_change %, curr/prev_median, n, reference_period)
    period = _period_expr(granularity)
    window = _RANKINGS_WINDOW_WEEKS[granularity]
    return f"""
    prices AS (
      SELECT {period} AS period, product_code, price_eur
      FROM {_silver_fq()}
      WHERE country_code = 'FR'
        AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
        AND product_code IS NOT NULL
        AND week_start_date IS NOT NULL
        AND week_start_date >= DATE_SUB(
          (SELECT MAX(week_start_date) FROM {_silver_fq()}),
          INTERVAL {window} WEEK
        )
    ),
    bucketed AS (
      SELECT
        period,
        product_code,
        APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price,
        COUNT(*) AS n
      FROM prices
      GROUP BY period, product_code
      HAVING COUNT(*) >= {_MIN_OBS}
    ),
    lagged AS (
      SELECT
        period,
        product_code,
        median_price,
        n,
        LAG(median_price) OVER (
          PARTITION BY product_code ORDER BY period
        ) AS prev_median
      FROM bucketed
    ),
    changes AS (
      SELECT
        period AS reference_period,
        product_code,
        prev_median,
        median_price AS curr_median,
        n,
        SAFE_DIVIDE(median_price - prev_median, NULLIF(prev_median, 0)) * 100 AS pct_change
      FROM lagged
      WHERE prev_median IS NOT NULL AND prev_median > 0
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY product_code ORDER BY period DESC
      ) = 1
    )
    """


def _silver_rankings_sql(direction: Literal["up", "down"], granularity: Granularity, limit: int) -> str:
    comparator = "> 0" if direction == "up" else "< 0"
    order = "DESC" if direction == "up" else "ASC"
    return f"""
    WITH {_silver_changes_cte(granularity)}
    SELECT
      ch.product_code AS ean,
      ch.pct_change,
      ch.curr_median AS price_eur_current,
      ch.prev_median AS price_eur_previous,
      ch.n AS sample_size,
      CAST(ch.reference_period AS STRING) AS period
    FROM changes ch
    WHERE ch.pct_change {comparator}
    ORDER BY ch.pct_change {order}
    LIMIT {int(limit)}
    """


@router.get("/rankings", response_model=RankingsOut)
async def get_rankings(
    limit: int = Query(default=20, ge=1, le=100),
    direction: Literal["up", "down"] = Query(default="up"),
    granularity: Granularity = Query(default="week"),
    session: AsyncSession = Depends(get_session),
) -> RankingsOut:
    settings = get_settings()

    rows: list[dict] = []
    # Gold rankings_produits : grain semaine + hausses only -> week/up seulement, sinon Silver
    if direction == "up" and granularity == "week":
        gold_sql = f"""
        SELECT
          r.product_code AS ean,
          r.pct_change * 100 AS pct_change,
          r.curr_median AS price_eur_current,
          r.prev_median AS price_eur_previous,
          CAST(r.reference_week AS STRING) AS period
        FROM {bq.qualified(settings.prt_bq_dataset_gold, 'rankings_produits')} r
        WHERE r.pct_change > 0
        ORDER BY r.pct_change DESC
        LIMIT {int(limit)}
        """
        rows = await asyncio.to_thread(
            bq.query_dicts_safe, gold_sql, context="observatoire_rankings_gold"
        )

    if not rows:
        rows = await asyncio.to_thread(
            bq.query_dicts_safe,
            _silver_rankings_sql(direction, granularity, limit),
            context=f"observatoire_rankings_{direction}_{granularity}",
        )

    resolved = await resolve_products(session, [r["ean"] for r in rows if r.get("ean")])
    period = rows[0].get("period") if rows else None
    return RankingsOut(period=period, items=_build_rankings(rows, resolved))


@router.get("/hall-of-shame", response_model=RankingsOut)
async def get_hall_of_shame(
    limit: int = Query(default=20, ge=1, le=100),
    granularity: Granularity = Query(default="week"),
    session: AsyncSession = Depends(get_session),
) -> RankingsOut:
    """Hausses ponderees par la popularite."""
    # shame_score calcule ici (pas en Gold) : pct_change * LN(1 + observations),
    # observations = proxy popularite
    sql = f"""
    WITH {_silver_changes_cte(granularity)}
    SELECT
      ch.product_code AS ean,
      ch.pct_change,
      ch.curr_median AS price_eur_current,
      ch.prev_median AS price_eur_previous,
      ch.n AS sample_size,
      CAST(ch.reference_period AS STRING) AS period
    FROM changes ch
    WHERE ch.pct_change > 0
    ORDER BY ch.pct_change * LN(1 + ch.n) DESC
    LIMIT {int(limit)}
    """
    rows = await asyncio.to_thread(
        bq.query_dicts_safe, sql, context=f"observatoire_hall_of_shame_{granularity}"
    )
    resolved = await resolve_products(session, [r["ean"] for r in rows if r.get("ean")])
    period = rows[0].get("period") if rows else None
    return RankingsOut(period=period, items=_build_rankings(rows, resolved))


@router.get("/map", response_model=MapOut)
async def get_map(granularity: Granularity = Query(default="week")) -> MapOut:
    """Choropleth : variation de prix par departement FR."""
    # Silver = seule source geolocalisee (postcode -> dept). Produits apparies
    # (limite l'effet de composition) : par (dept, produit) mediane N dernieres
    # semaines vs N precedentes, moyenne ponderee par les observations
    half = _MAP_HALF_WINDOW_WEEKS[granularity]
    sql = f"""
    WITH prices AS (
      SELECT
        ({bq.DEPT_FROM_POSTCODE_SQL}) AS departement,
        week_start_date,
        product_code,
        price_eur
      FROM {_silver_fq()}
      WHERE country_code = 'FR'
        AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
        AND postcode IS NOT NULL
        AND product_code IS NOT NULL
        AND week_start_date IS NOT NULL
    ),
    anchor AS (SELECT MAX(week_start_date) AS maxw FROM prices),
    halves AS (
      SELECT
        p.departement,
        p.product_code,
        IF(p.week_start_date > DATE_SUB(a.maxw, INTERVAL {half} WEEK),
           'recent', 'previous') AS half,
        p.price_eur
      FROM prices p, anchor a
      WHERE p.week_start_date > DATE_SUB(a.maxw, INTERVAL {2 * half} WEEK)
    ),
    med AS (
      SELECT
        departement,
        product_code,
        half,
        APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price,
        COUNT(*) AS n
      FROM halves
      GROUP BY departement, product_code, half
      HAVING COUNT(*) >= 2
    ),
    matched AS (
      SELECT
        r.departement,
        r.product_code,
        SAFE_DIVIDE(r.median_price - p.median_price, NULLIF(p.median_price, 0)) * 100
          AS pct_change,
        r.n + p.n AS n
      FROM med r
      JOIN med p
        ON p.departement = r.departement
       AND p.product_code = r.product_code
       AND p.half = 'previous'
      WHERE r.half = 'recent'
    )
    SELECT
      m.departement,
      SAFE_DIVIDE(SUM(m.pct_change * m.n), SUM(m.n)) AS inflation_pct,
      SUM(m.n) AS sample_size,
      CAST(ANY_VALUE(a.maxw) AS STRING) AS period
    FROM matched m, anchor a
    GROUP BY m.departement
    """
    rows = await asyncio.to_thread(bq.query_dicts_safe, sql, context=f"observatoire_map_{granularity}")
    period = rows[0].get("period") if rows else None
    values = [
        MapDepartementValue(
            departement=r["departement"],
            inflation_pct=float(r["inflation_pct"]) if r.get("inflation_pct") is not None else None,
            sample_size=int(r["sample_size"]) if r.get("sample_size") is not None else None,
        )
        for r in rows
        if r.get("departement")
    ]
    return MapOut(period=period, values=values)
