"""Router products — detail + recherche + substituts sur Cloud SQL products,
prix sur BQ Silver open_prices_clean.

Catalogue = source de verite Cloud SQL products (plus complet que le miroir BQ
catalogue_produits). 3 etats par EAN : absent -> 404 ; present off_found=false ->
200 champs OFF NULL (on garde la trace, evite de retenter) ; enrichi -> 200 complet.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.cloud import bigquery
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import bq
from ..config import get_settings
from ..db import get_session
from ..logging import get_logger
from ..models.products import Product
from ..schemas.products import (
    PricePoint,
    ProductOut,
    ProductPricesOut,
    ProductSearchResult,
    StorePrice,
    SubstituteOut,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/products", tags=["products"])


def _row_to_product(row: dict) -> ProductOut:
    # NULL-tolerant sur les colonnes OFF
    return ProductOut(
        ean=row["ean"],
        name=row.get("name"),
        brand=row.get("brand"),
        category_l1=row.get("category_l1"),
        category_l2=row.get("category_l2"),
        category_l3=row.get("category_l3"),
        nutriscore=row.get("nutriscore"),
        nova=row.get("nova"),
        ecoscore=row.get("ecoscore"),
        image_url=row.get("image_url"),
        off_found=bool(row.get("off_found", False)),
        source=row.get("source"),
    )


# /search doit etre declare AVANT /{ean} sinon "search" est capture comme ean


@router.get("/search", response_model=ProductSearchResult)
async def search_products(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> ProductSearchResult:
    """Recherche par nom, marque ou debut d'EAN."""
    # filtre off_found=TRUE (non enrichis = name/brand NULL) ; escape %/_ pour ILIKE litteral
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    sql = text(
        """
        SELECT ean, name, brand, category_l1, category_l2, category_l3,
               nutriscore, nova, ecoscore, image_url, off_found, source
        FROM products
        WHERE off_found = TRUE
          AND (
            name ILIKE :pattern
            OR brand ILIKE :pattern
            OR ean LIKE :ean_prefix
          )
        ORDER BY name
        LIMIT :limit
        """
    )
    result = await session.execute(
        sql,
        {"pattern": f"%{escaped}%", "ean_prefix": f"{escaped}%", "limit": limit},
    )
    rows = result.mappings().all()
    items = [_row_to_product(dict(r)) for r in rows]
    return ProductSearchResult(items=items, total=len(items))


@router.get("/{ean}", response_model=ProductOut)
async def get_product(
    ean: str,
    session: AsyncSession = Depends(get_session),
) -> ProductOut:
    row = await session.get(Product, ean)
    if row is not None:
        return ProductOut(
            ean=row.ean,
            name=row.name,
            brand=row.brand,
            category_l1=row.category_l1,
            category_l2=row.category_l2,
            category_l3=row.category_l3,
            nutriscore=row.nutriscore,
            nova=row.nova,
            ecoscore=row.ecoscore,
            image_url=row.image_url,
            off_found=bool(row.off_found),
            catalog=True,
            source=row.source,
        )

    # hors catalogue : EAN connu par ses seuls prix Silver -> fiche prix seulement
    # (200, catalog=false) pour ne pas casser le clic observatoire ; 404 si nulle part
    settings = get_settings()
    src = bq.qualified(settings.prt_bq_dataset_silver, "open_prices_clean")
    exists = await asyncio.to_thread(
        bq.query_dicts_safe,
        f"SELECT 1 AS ok FROM {src} WHERE product_code = @ean LIMIT 1",
        params=[bigquery.ScalarQueryParameter("ean", "STRING", ean)],
        context=f"product_price_only_probe_{ean}",
    )
    if exists:
        return ProductOut(ean=ean, off_found=False, catalog=False)
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"EAN {ean!r} not in catalog.")


@router.get("/{ean}/prices", response_model=ProductPricesOut)
async def get_product_prices(ean: str) -> ProductPricesOut:
    """Historique de prix + comparateur enseignes pour un EAN."""
    # series = mediane hebdo tous PDV ; by_store = mediane par enseigne sur les 8
    # dernieres semaines DU PRODUIT (ancre sur son MAX(week), pas CURRENT_DATE :
    # robuste aux retards d'ingestion). EAN jamais releve -> payload vide (200).
    settings = get_settings()
    src = bq.qualified(settings.prt_bq_dataset_silver, "open_prices_clean")
    ean_param = [bigquery.ScalarQueryParameter("ean", "STRING", ean)]

    series_sql = f"""
    SELECT
      week_start_date AS week,
      APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur,
      COUNT(*) AS observations
    FROM {src}
    WHERE product_code = @ean
      AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
      AND week_start_date IS NOT NULL
    GROUP BY week_start_date
    ORDER BY week_start_date
    """
    stores_sql = f"""
    WITH anchor AS (
      SELECT MAX(week_start_date) AS maxw FROM {src} WHERE product_code = @ean
    )
    SELECT
      store_brand_normalized AS enseigne,
      APPROX_QUANTILES(price_eur, 100)[OFFSET(50)] AS median_price_eur,
      COUNT(*) AS observations,
      MAX(week_start_date) AS last_seen_week
    FROM {src}, anchor
    WHERE product_code = @ean
      AND (iqr_outlier IS NULL OR iqr_outlier = FALSE)
      AND store_brand_normalized IS NOT NULL
      AND week_start_date > DATE_SUB(anchor.maxw, INTERVAL 8 WEEK)
    GROUP BY store_brand_normalized
    ORDER BY median_price_eur ASC
    """
    series_rows, store_rows = await asyncio.gather(
        asyncio.to_thread(
            bq.query_dicts_safe, series_sql, params=ean_param, context=f"product_prices_{ean}"
        ),
        asyncio.to_thread(
            bq.query_dicts_safe, stores_sql, params=ean_param, context=f"product_stores_{ean}"
        ),
    )

    series = [
        PricePoint(
            week=r["week"],
            median_price_eur=float(r["median_price_eur"]),
            observations=int(r["observations"]),
        )
        for r in series_rows
        if r.get("median_price_eur") is not None
    ]
    by_store = [
        StorePrice(
            enseigne=r["enseigne"],
            median_price_eur=float(r["median_price_eur"]),
            observations=int(r["observations"]),
            last_seen_week=r.get("last_seen_week"),
        )
        for r in store_rows
        if r.get("median_price_eur") is not None
    ]

    latest = series[-1].median_price_eur if series else None
    pct = None
    if len(series) >= 2 and series[0].median_price_eur > 0:
        pct = (series[-1].median_price_eur / series[0].median_price_eur - 1) * 100

    return ProductPricesOut(
        ean=ean,
        series=series,
        by_store=by_store,
        latest_median_eur=latest,
        pct_change_window=pct,
    )


@router.get("/{ean}/substitutes", response_model=list[SubstituteOut])
async def get_substitutes(
    ean: str,
    k: int = Query(default=5, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> list[SubstituteOut]:
    """Top-K substituts via pgvector cosine similarity."""
    # K plus proches (hors EAN cible) partageant category_l3 (pas de shampoing -> yaourt).
    # embedding target NULL -> 404 ; moins de K voisins -> renvoie ce qu'on a
    sql = text(
        """
        WITH target AS (
            SELECT embedding, category_l3
            FROM products
            WHERE ean = :ean AND embedding IS NOT NULL
        )
        SELECT
            p.ean, p.name, p.brand, p.category_l1, p.category_l2, p.category_l3,
            p.nutriscore, p.nova, p.ecoscore, p.image_url, p.off_found, p.source,
            1 - (p.embedding <=> t.embedding) AS similarity
        FROM products p, target t
        WHERE p.ean <> :ean
          AND p.embedding IS NOT NULL
          AND p.category_l3 = t.category_l3
        ORDER BY p.embedding <=> t.embedding ASC
        LIMIT :k
        """
    )
    result = await session.execute(sql, {"ean": ean, "k": k})
    rows = result.mappings().all()
    if not rows:
        # pas d'embedding ou pas de voisin : verifie l'existence pour distinguer
        # 404 produit inconnu vs [] pas de voisins
        exists = await session.execute(
            text("SELECT 1 FROM products WHERE ean = :ean"), {"ean": ean}
        )
        if exists.scalar_one_or_none() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"EAN {ean!r} unknown.")
        return []

    return [
        SubstituteOut(
            ean=r["ean"],
            name=r["name"],
            brand=r["brand"],
            category_l1=r["category_l1"],
            category_l2=r["category_l2"],
            category_l3=r["category_l3"],
            nutriscore=r["nutriscore"],
            nova=r["nova"],
            ecoscore=r["ecoscore"],
            image_url=r["image_url"],
            off_found=bool(r["off_found"]),
            source=r["source"],
            similarity=float(r["similarity"]) if r["similarity"] is not None else 0.0,
        )
        for r in rows
    ]
