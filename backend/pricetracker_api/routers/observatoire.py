"""Router observatoire public — rankings, hall of shame, carte.

Schémas RÉELS (cf. workers/indices/pricetracker_indices/bq.py) :
- Gold `rankings_produits` : (reference_week, product_code, prev_median,
  curr_median, pct_change RATIO) — top hausses uniquement, sans nom/marque.
- Silver `open_prices_clean` : prix unitaires (postcode, enseigne, semaine).
- Silver `catalogue_produits` : nom/marque par EAN (join d'affichage).

Les baisses et le hall of shame ne sont pas matérialisés côté Gold : ils
sont dérivés de Silver ici (médianes hebdo par produit + LAG, fenêtre
ancrée sur MAX(week_start_date)). Les hausses lisent Gold en priorité
(table matérialisée = moins cher) avec repli Silver si le worker n'a pas
encore publié.

Si les tables ne sont pas peuplées, on renvoie un payload vide (200,
items=[]) plutôt que 500 : le frontend affiche un état « observatoire en
construction ».
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Query

from .. import bq
from ..config import get_settings
from ..schemas.indices import (
    MapDepartementValue,
    MapOut,
    RankingItem,
    RankingsOut,
)

router = APIRouter(prefix="/observatoire", tags=["observatoire"])

_RANKINGS_WINDOW_WEEKS = 8
_MAP_HALF_WINDOW_WEEKS = 4
_MIN_OBS = 3


def _row_to_ranking(r: dict) -> RankingItem:
    return RankingItem(
        ean=r.get("ean"),
        produit_nom=r.get("produit_nom"),
        brand=r.get("brand"),
        pct_change=float(r["pct_change"]) if r.get("pct_change") is not None else 0.0,
        price_eur_current=r.get("price_eur_current"),
        price_eur_previous=r.get("price_eur_previous"),
        sample_size=r.get("sample_size"),
    )


def _catalogue_fq() -> str:
    settings = get_settings()
    return bq.qualified(settings.prt_bq_dataset_silver, settings.prt_bq_table_catalogue)


def _silver_fq() -> str:
    settings = get_settings()
    return bq.qualified(settings.prt_bq_dataset_silver, "open_prices_clean")


def _silver_changes_cte() -> str:
    """CTE partagée : dernière variation hebdo (médiane) par produit sur la
    fenêtre rankings, calculée depuis Silver. Expose (product_code, pct_change
    en %, curr_median, prev_median, n, reference_week)."""
    return f"""
    prices AS (
      SELECT week_start_date, product_code, price_eur
      FROM {_silver_fq()}
      WHERE country_code = 'FR'
        AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
        AND product_code IS NOT NULL
        AND week_start_date IS NOT NULL
        AND week_start_date >= DATE_SUB(
          (SELECT MAX(week_start_date) FROM {_silver_fq()}),
          INTERVAL {_RANKINGS_WINDOW_WEEKS} WEEK
        )
    ),
    weekly AS (
      SELECT
        week_start_date,
        product_code,
        APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price,
        COUNT(*) AS n
      FROM prices
      GROUP BY week_start_date, product_code
      HAVING COUNT(*) >= {_MIN_OBS}
    ),
    lagged AS (
      SELECT
        week_start_date,
        product_code,
        median_price,
        n,
        LAG(median_price) OVER (
          PARTITION BY product_code ORDER BY week_start_date
        ) AS prev_median
      FROM weekly
    ),
    changes AS (
      SELECT
        week_start_date AS reference_week,
        product_code,
        prev_median,
        median_price AS curr_median,
        n,
        SAFE_DIVIDE(median_price - prev_median, NULLIF(prev_median, 0)) * 100 AS pct_change
      FROM lagged
      WHERE prev_median IS NOT NULL AND prev_median > 0
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY product_code ORDER BY week_start_date DESC
      ) = 1
    )
    """


def _silver_rankings_sql(direction: Literal["up", "down"], limit: int) -> str:
    comparator = "> 0" if direction == "up" else "< 0"
    order = "DESC" if direction == "up" else "ASC"
    return f"""
    WITH {_silver_changes_cte()}
    SELECT
      ch.product_code AS ean,
      c.name AS produit_nom,
      c.brand,
      ch.pct_change,
      ch.curr_median AS price_eur_current,
      ch.prev_median AS price_eur_previous,
      ch.n AS sample_size,
      CAST(ch.reference_week AS STRING) AS period
    FROM changes ch
    LEFT JOIN {_catalogue_fq()} c ON c.ean = ch.product_code
    WHERE ch.pct_change {comparator}
    ORDER BY ch.pct_change {order}
    LIMIT {int(limit)}
    """


@router.get("/rankings", response_model=RankingsOut)
async def get_rankings(
    limit: int = Query(default=20, ge=1, le=100),
    direction: Literal["up", "down"] = Query(default="up"),
) -> RankingsOut:
    settings = get_settings()

    rows: list[dict] = []
    if direction == "up":
        # Gold d'abord (matérialisé par le worker indices). pct_change y est
        # un ratio → conversion en % pour respecter le contrat RankingItem.
        gold_sql = f"""
        SELECT
          r.product_code AS ean,
          c.name AS produit_nom,
          c.brand,
          r.pct_change * 100 AS pct_change,
          r.curr_median AS price_eur_current,
          r.prev_median AS price_eur_previous,
          CAST(r.reference_week AS STRING) AS period
        FROM {bq.qualified(settings.prt_bq_dataset_gold, 'rankings_produits')} r
        LEFT JOIN {_catalogue_fq()} c ON c.ean = r.product_code
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
            _silver_rankings_sql(direction, limit),
            context=f"observatoire_rankings_{direction}",
        )

    period = rows[0].get("period") if rows else None
    return RankingsOut(period=period, items=[_row_to_ranking(r) for r in rows])


@router.get("/hall-of-shame", response_model=RankingsOut)
async def get_hall_of_shame(limit: int = Query(default=20, ge=1, le=100)) -> RankingsOut:
    """Hausses les plus « visibles » : variation pondérée par la popularité.

    Aucun `shame_score` n'est matérialisé côté Gold — on le calcule ici :
    pct_change × LN(1 + observations), les observations servant de proxy
    de popularité (plus un produit est relevé, plus il est acheté/suivi).
    """
    sql = f"""
    WITH {_silver_changes_cte()}
    SELECT
      ch.product_code AS ean,
      c.name AS produit_nom,
      c.brand,
      ch.pct_change,
      ch.curr_median AS price_eur_current,
      ch.prev_median AS price_eur_previous,
      ch.n AS sample_size,
      CAST(ch.reference_week AS STRING) AS period
    FROM changes ch
    LEFT JOIN {_catalogue_fq()} c ON c.ean = ch.product_code
    WHERE ch.pct_change > 0
    ORDER BY ch.pct_change * LN(1 + ch.n) DESC
    LIMIT {int(limit)}
    """
    rows = await asyncio.to_thread(
        bq.query_dicts_safe, sql, context="observatoire_hall_of_shame"
    )
    period = rows[0].get("period") if rows else None
    return RankingsOut(period=period, items=[_row_to_ranking(r) for r in rows])


@router.get("/map", response_model=MapOut)
async def get_map() -> MapOut:
    """Choroplèthe : variation de prix par département FR.

    Silver est la seule source géolocalisée (postcode → département).
    Méthode « produits appariés » pour limiter l'effet de composition :
    par (département, produit), médiane des {_MAP_HALF_WINDOW_WEEKS}
    dernières semaines vs les {_MAP_HALF_WINDOW_WEEKS} précédentes, puis
    moyenne des variations pondérée par le nombre d'observations.
    """
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
        IF(p.week_start_date > DATE_SUB(a.maxw, INTERVAL {_MAP_HALF_WINDOW_WEEKS} WEEK),
           'recent', 'previous') AS half,
        p.price_eur
      FROM prices p, anchor a
      WHERE p.week_start_date > DATE_SUB(a.maxw, INTERVAL {2 * _MAP_HALF_WINDOW_WEEKS} WEEK)
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
    rows = await asyncio.to_thread(bq.query_dicts_safe, sql, context="observatoire_map")
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
