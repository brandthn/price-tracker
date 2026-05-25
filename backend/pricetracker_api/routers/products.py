"""Router products — détail + recherche (BQ catalogue) + substituts (pgvector).

Important : le catalogue est partiel (worker OFF rate-limité à 15 rpm).
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
from ..schemas.products import ProductOut, ProductSearchResult, SubstituteOut

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
) -> ProductSearchResult:
    """Recherche full-text simple sur name + brand. Tolère les EAN avec NULL
    name/brand : ces lignes sont juste exclues du LIKE et donc des résultats.
    """
    settings = get_settings()
    sql = f"""
    SELECT ean, name, brand, category_l1, category_l2, category_l3,
           nutriscore, nova, ecoscore, image_url, off_found, source
    FROM {bq.qualified(settings.prt_bq_dataset_silver, settings.prt_bq_table_catalogue)}
    WHERE off_found = TRUE
      AND (
        LOWER(name) LIKE CONCAT('%', LOWER(@q), '%')
        OR LOWER(brand) LIKE CONCAT('%', LOWER(@q), '%')
      )
    ORDER BY name
    LIMIT @limit
    """
    rows = await asyncio.to_thread(
        bq.query_dicts,
        sql,
        params=[
            bigquery.ScalarQueryParameter("q", "STRING", q),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ],
    )
    items = [_row_to_product(r) for r in rows]
    return ProductSearchResult(items=items, total=len(items))


@router.get("/{ean}", response_model=ProductOut)
async def get_product(ean: str) -> ProductOut:
    settings = get_settings()
    sql = f"""
    SELECT ean, name, brand, category_l1, category_l2, category_l3,
           nutriscore, nova, ecoscore, image_url, off_found, source
    FROM {bq.qualified(settings.prt_bq_dataset_silver, settings.prt_bq_table_catalogue)}
    WHERE ean = @ean
    LIMIT 1
    """
    rows = await asyncio.to_thread(
        bq.query_dicts,
        sql,
        params=[bigquery.ScalarQueryParameter("ean", "STRING", ean)],
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"EAN {ean!r} not in catalog.")
    return _row_to_product(rows[0])


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
