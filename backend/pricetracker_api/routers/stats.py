"""Router stats — agrégations par marque (observatoire enrichi)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, status
from google.cloud import bigquery

from .. import bq
from ..config import get_settings
from ..schemas.indices import BrandStatsOut, RankingItem

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/brand/{brand}", response_model=BrandStatsOut)
async def get_brand_stats(brand: str) -> BrandStatsOut:
    """Stats agrégées par marque : nombre de produits, prix moyen, médiane
    de variation, top hausses. Source : `catalogue_produits` (Silver) +
    `aggregats_enseignes` / `rankings_produits` (Gold).

    Tolère les tables Gold absentes (worker indices pas livré) : la partie
    `median_pct_change` + `top_increases` sera vide, mais `product_count`
    et `avg_price_eur` peuvent être renseignés depuis Silver + Open Prices.
    """
    settings = get_settings()

    # 1) Aggrégat Silver — nombre de produits enrichis + prix moyen.
    # Le prix moyen vient d'`open_prices_clean` joint au catalogue.
    silver_sql = f"""
    SELECT
      COUNT(DISTINCT c.ean) AS product_count,
      AVG(op.price_eur) AS avg_price_eur
    FROM {bq.qualified(settings.prt_bq_dataset_silver, settings.prt_bq_table_catalogue)} c
    LEFT JOIN {bq.qualified(settings.prt_bq_dataset_silver, 'open_prices_clean')} op
      ON op.product_code = c.ean AND op.iqr_outlier = FALSE
    WHERE LOWER(c.brand) = LOWER(@brand)
    """
    silver_rows = await asyncio.to_thread(
        bq.query_dicts_safe,
        silver_sql,
        params=[bigquery.ScalarQueryParameter("brand", "STRING", brand)],
        context=f"stats_brand_silver_{brand}",
    )
    silver = silver_rows[0] if silver_rows else {}
    product_count = int(silver.get("product_count") or 0)
    if product_count == 0:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Brand {brand!r} not in catalog."
        )

    # 2) Médiane variation — depuis Gold rankings_produits.
    gold_sql = f"""
    SELECT
      APPROX_QUANTILES(pct_change, 100)[OFFSET(50)] AS median_pct_change
    FROM {bq.qualified(settings.prt_bq_dataset_gold, 'rankings_produits')}
    WHERE LOWER(brand) = LOWER(@brand)
    """
    gold_rows = await asyncio.to_thread(
        bq.query_dicts_safe,
        gold_sql,
        params=[bigquery.ScalarQueryParameter("brand", "STRING", brand)],
        context=f"stats_brand_gold_{brand}",
    )
    median_pct_change = gold_rows[0].get("median_pct_change") if gold_rows else None

    # 3) Top hausses pour cette marque.
    top_sql = f"""
    SELECT ean, produit_nom, brand, pct_change, price_eur_current,
           price_eur_previous, sample_size
    FROM {bq.qualified(settings.prt_bq_dataset_gold, 'rankings_produits')}
    WHERE LOWER(brand) = LOWER(@brand)
      AND category = 'top_increases'
    ORDER BY pct_change DESC
    LIMIT 5
    """
    top_rows = await asyncio.to_thread(
        bq.query_dicts_safe,
        top_sql,
        params=[bigquery.ScalarQueryParameter("brand", "STRING", brand)],
        context=f"stats_brand_top_{brand}",
    )
    top_increases = [
        RankingItem(
            ean=r.get("ean"),
            produit_nom=r.get("produit_nom"),
            brand=r.get("brand"),
            pct_change=float(r["pct_change"]) if r.get("pct_change") is not None else 0.0,
            price_eur_current=r.get("price_eur_current"),
            price_eur_previous=r.get("price_eur_previous"),
            sample_size=r.get("sample_size"),
        )
        for r in top_rows
    ]

    return BrandStatsOut(
        brand=brand,
        product_count=product_count,
        avg_price_eur=float(silver["avg_price_eur"]) if silver.get("avg_price_eur") else None,
        median_pct_change=float(median_pct_change) if median_pct_change is not None else None,
        top_increases=top_increases,
    )
