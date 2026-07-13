#Cloud SQL helpers for products

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import asyncpg
import numpy as np

from .logging import get_logger
from .off_client import OFFProduct
from .quantity import normalize_quantity

logger = get_logger(__name__)


def _vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"


def _quantity_numeric(value: float | None) -> Decimal | None:
    #float canonique (kg/L) → Decimal pour la colonne NUMERIC (asyncpg exige un Decimal, pas un float, sur un type `numeric`), None passe tel quel
    return Decimal(str(value)) if value is not None else None


async def open_pool(
    *,
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
    min_size: int = 1,
    max_size: int = 4,
) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        host=host,
        port=port,
        database=db,
        user=user,
        password=password,
        min_size=min_size,
        max_size=max_size,
        timeout=10.0,
        command_timeout=30.0,
    )


async def upsert_products(
    pool: asyncpg.Pool,
    *,
    products: Sequence[OFFProduct],
    embeddings: Sequence[Sequence[float] | None],
    source: str = "openfoodfacts",
) -> int:
    #Insert or update products and embeddings
    if len(products) != len(embeddings):
        raise ValueError("products and embeddings must have the same length.")

    if not products:
        return 0

    sql = """
    INSERT INTO products (
        ean, name, brand, category_l1, category_l2, category_l3,
        nutriscore, nova, ecoscore, image_url, off_found, embedding,
        enriched_at, source, quantity_raw, quantity_value, quantity_unit,
        categories_tags
    )
    VALUES (
        $1, $2, $3, $4, $5, $6,
        $7, $8, $9, $10, $11,
        CASE WHEN $12::text IS NULL THEN NULL ELSE $12::vector END,
        now(), $13, $14, $15, $16, $17
    )
    ON CONFLICT (ean) DO UPDATE SET
        name = EXCLUDED.name,
        brand = EXCLUDED.brand,
        category_l1 = EXCLUDED.category_l1,
        category_l2 = EXCLUDED.category_l2,
        category_l3 = EXCLUDED.category_l3,
        nutriscore = EXCLUDED.nutriscore,
        nova = EXCLUDED.nova,
        ecoscore = EXCLUDED.ecoscore,
        image_url = EXCLUDED.image_url,
        off_found = EXCLUDED.off_found,
        embedding = COALESCE(EXCLUDED.embedding, products.embedding),
        enriched_at = EXCLUDED.enriched_at,
        source = EXCLUDED.source,
        quantity_raw = EXCLUDED.quantity_raw,
        quantity_value = EXCLUDED.quantity_value,
        quantity_unit = EXCLUDED.quantity_unit,
        categories_tags = EXCLUDED.categories_tags
    """
    written = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for prod, emb in zip(products, embeddings, strict=True):
                qty_value, qty_unit = normalize_quantity(
                    prod.product_quantity, prod.product_quantity_unit
                )
                args: list[Any] = [
                    prod.ean,
                    prod.name,
                    prod.brand,
                    prod.category_l1,
                    prod.category_l2,
                    prod.category_l3,
                    prod.nutriscore,
                    prod.nova,
                    prod.ecoscore,
                    prod.image_url,
                    prod.found,
                    _vector_literal(emb) if emb is not None else None,
                    source,
                    prod.quantity,
                    _quantity_numeric(qty_value),
                    qty_unit,
                    prod.categories_tags,
                ]
                await conn.execute(sql, *args)
                written += 1
    logger.info("pg_upsert_done", rows=written, source=source)
    return written


async def update_embeddings(
    pool: asyncpg.Pool,
    *,
    products: Sequence[OFFProduct],
    embeddings: Sequence[Sequence[float] | None],
) -> dict[str, int]:
    """- Ignore les entrées sans embedding, rien à mettre à jour
    - Un EAN absent de `products` → l'UPDATE matche 0 ligne

    Retourne {'candidates': N, 'updated': M} où `updated` = lignes réellement
    modifiées (M ≤ N si des EAN ne sont pas en base)
    """
    if len(products) != len(embeddings):
        raise ValueError("products and embeddings must have the same length.")

    sql = "UPDATE products SET embedding = $1::vector WHERE ean = $2"
    candidates = 0
    updated = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for prod, emb in zip(products, embeddings, strict=True):
                if emb is None:
                    continue
                candidates += 1
                status = await conn.execute(sql, _vector_literal(emb), prod.ean)
                # asyncpg renvoie "UPDATE <n>" — n = lignes matchées (0 si EAN absent)
                try:
                    updated += int(status.split()[-1])
                except (ValueError, IndexError):
                    pass
    logger.info("pg_update_embeddings_done", candidates=candidates, updated=updated)
    return {"candidates": candidates, "updated": updated}


async def update_reco_columns(
    pool: asyncpg.Pool,
    *,
    products: Sequence[OFFProduct],
) -> dict[str, int]:
    """Backfill des colonnes socle reco sur les produits DÉJÀ en base

    Même garde-fou que `update_embeddings`

    - quantité : `(value, unit)` via `normalize_quantity` (g→kg, ml→L) ; sans unité
      propre → value/unit NULL (exclu du €/unité), `quantity_raw` garde le texte OFF ;
    - `categories_tags` : chemin OFF complet (pour la profondeur de préfixe commun), NULL si absent

    Retourne {'candidates': N, 'updated': M} — M ≤ N si des EAN ne sont pas en base
    """
    sql = """
    UPDATE products
    SET quantity_raw = $2, quantity_value = $3, quantity_unit = $4,
        categories_tags = $5
    WHERE ean = $1
    """
    candidates = 0
    updated = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for prod in products:
                candidates += 1
                qty_value, qty_unit = normalize_quantity(
                    prod.product_quantity, prod.product_quantity_unit
                )
                status = await conn.execute(
                    sql,
                    prod.ean,
                    prod.quantity,
                    _quantity_numeric(qty_value),
                    qty_unit,
                    prod.categories_tags,
                )
                try:
                    updated += int(status.split()[-1])
                except (ValueError, IndexError):
                    pass
    logger.info("pg_update_reco_columns_done", candidates=candidates, updated=updated)
    return {"candidates": candidates, "updated": updated}


# Calcul des paires substitut→produit


async def fetch_scorable_products(
    pool: asyncpg.Pool,
) -> tuple[dict[str, dict[str, Any]], list[str], np.ndarray]:
    sql = """
    SELECT ean, name, brand, category_l3, categories_tags,
           quantity_value, quantity_unit, embedding::text AS emb
    FROM products
    WHERE embedding IS NOT NULL
      AND quantity_value IS NOT NULL
      AND quantity_unit IS NOT NULL
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, timeout=300)

    meta: dict[str, dict[str, Any]] = {}
    eans: list[str] = []
    vectors: list[np.ndarray] = []
    for r in rows:
        tags = r["categories_tags"]
        ean = r["ean"]
        meta[ean] = {
            "name": r["name"],
            "brand": r["brand"],
            "category_l3": r["category_l3"],
            "categories_tags": list(tags) if tags is not None else None,
            "quantity_value": float(r["quantity_value"]),
            "quantity_unit": r["quantity_unit"],
        }
        eans.append(ean)
        vectors.append(np.fromstring(r["emb"][1:-1], sep=",", dtype=np.float32))

    embeddings = np.vstack(vectors) if vectors else np.empty((0, 0), dtype=np.float32)
    logger.info("pg_fetch_scorable_done", products=len(eans))
    return meta, eans, embeddings


async def write_substitutions(
    pool: asyncpg.Pool, rows: Sequence[tuple[Any, ...]]
) -> int:
    if not rows:
        logger.warning("pg_write_substitutions_empty")
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE TABLE product_substitutions")
        return 0

    insert = """
    INSERT INTO product_substitutions (
        source_ean, target_ean, tier, score, cosine, cat_agreement, quantity_unit,
        source_price_per_unit, target_price_per_unit, saving_per_unit, saving_pct,
        source_price_obs, target_price_obs
    ) VALUES (
        $1, $2, $3, $4::float8, $5::float8, $6::float8, $7,
        $8::float8, $9::float8, $10::float8, $11::float8, $12, $13
    )
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE TABLE product_substitutions")
            await conn.executemany(insert, rows)
    logger.info("pg_write_substitutions_done", rows=len(rows))
    return len(rows)
