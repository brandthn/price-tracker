"""Router products — détail + recherche + substituts sur Cloud SQL `products`,
prix sur BQ Silver `open_prices_clean`.

Source de vérité du catalogue : Cloud SQL `products` (~14k EANs, 12k enrichis
via OFF bulk + worker quotidien) — beaucoup plus complet que le miroir BQ
`catalogue_produits`, qui ne sert plus ici qu'aux joins d'affichage des
requêtes analytiques (observatoire/stats).

On distingue 3 états par EAN :
  1. EAN absent de la table : renvoie 404.
  2. EAN présent avec `off_found=false` : renvoie 200 avec champs OFF NULL.
     Le frontend doit afficher "Données enrichies en cours" plutôt qu'un
     placeholder vide. C'est intentionnel : on garde la trace de l'EAN même
     si OFF ne l'a pas (évite de retenter à chaque run).
  3. EAN enrichi : 200 avec tous les champs.
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
    """Convertit une row BQ catalogue_produits en ProductOut. NULL-tolerant
    sur les colonnes OFF (worker OFF rate-limité)."""
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


# Ordre déclaratif important : `/search` doit être enregistré AVANT
# `/{ean}` sinon FastAPI résout `/products/search` comme ean="search".


@router.get("/search", response_model=ProductSearchResult)
async def search_products(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> ProductSearchResult:
    """Recherche par nom, marque ou début d'EAN sur Cloud SQL `products`.

    Filtre `off_found = TRUE` : les EAN non enrichis ont name/brand NULL,
    inutilisables en résultat de recherche. L'ILIKE échappe %/_ pour que la
    saisie utilisateur soit traitée littéralement.
    """
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
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"EAN {ean!r} not in catalog.")
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
        source=row.source,
    )


@router.get("/{ean}/prices", response_model=ProductPricesOut)
async def get_product_prices(ean: str) -> ProductPricesOut:
    """Historique de prix + comparateur enseignes pour un EAN.

    Source : Silver `open_prices_clean` (relevés Open Prices géolocalisés).
    - `series` : médiane hebdo tous points de vente confondus (toute la
      profondeur disponible — la fenêtre Open Prices est encore courte).
    - `by_store` : médiane par enseigne sur les 8 dernières semaines DE CE
      PRODUIT (ancrées sur son MAX(week), pas CURRENT_DATE : robuste aux
      retards d'ingestion), triée du moins cher au plus cher.

    Un EAN jamais relevé renvoie un payload vide (200) : le produit peut
    exister au catalogue sans avoir de prix publics — état à afficher
    honnêtement côté frontend.
    """
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
    """Top-K substituts via pgvector cosine similarity.

    Lit l'embedding de l'EAN cible depuis Cloud SQL `products.embedding`,
    cherche les K plus proches (excluant l'EAN lui-même) qui partagent la
    même `category_l3` (sécurité : pas de substitut shampoing → yaourt).

    Edge cases :
    - EAN target absent / embedding NULL → 404 (substituts pas calculables).
    - Moins de K voisins dans la catégorie → renvoie ce qu'on a (peut être []).
    """
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
        # Soit l'EAN cible n'a pas d'embedding (worker OFF pas passé sur lui),
        # soit aucun voisin dans la même catégorie. Distinguer via une query
        # supplémentaire ajouterait du coût et peu de valeur ; on renvoie 404
        # dans les deux cas. Le frontend peut afficher "Pas de substituts dispo".
        # Vérifie si l'EAN existe au moins pour différencier "produit inconnu"
        # vs "pas de voisins" :
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
