"""Mirror Cloud SQL `products` (pgvector) via asyncpg.

Connexion : private IP de `prt-prod-sql-main` joignable depuis Cloud Run via
Direct VPC egress (subnet `prt-subnet-ew1`). User `pt_app` + password lu en
Secret Manager (`prt-prod-cloudsql-password`).

Le vecteur pgvector se passe en littéral `'[v1,v2,...]'::vector(768)`.
asyncpg ne sait pas serialiser un `list[float]` en `vector` nativement, on
encode côté Python.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import asyncpg

from .logging import get_logger
from .off_client import OFFProduct

logger = get_logger(__name__)


def _vector_literal(vec: Sequence[float]) -> str:
    # pgvector accepte '[1.0,2.0,...]' en text — convertit côté SQL via
    # le cast `::vector(768)`. Float repr Python est suffisamment précis.
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"


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
) -> int:
    """INSERT … ON CONFLICT (ean) DO UPDATE. Retourne le nombre de rows écrits.

    `embeddings[i]` correspond à `products[i]` ; `None` autorisé (cas `off_found=false`
    où l'embedding n'a pas été calculé).
    """
    if len(products) != len(embeddings):
        raise ValueError("products and embeddings must have the same length.")

    if not products:
        return 0

    sql = """
    INSERT INTO products (
        ean, name, brand, category_l1, category_l2, category_l3,
        nutriscore, nova, ecoscore, image_url, off_found, embedding,
        enriched_at, source
    )
    VALUES (
        $1, $2, $3, $4, $5, $6,
        $7, $8, $9, $10, $11,
        CASE WHEN $12::text IS NULL THEN NULL ELSE $12::vector END,
        now(), 'openfoodfacts'
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
        source = EXCLUDED.source
    """
    written = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for prod, emb in zip(products, embeddings, strict=True):
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
                ]
                await conn.execute(sql, *args)
                written += 1
    logger.info("pg_upsert_done", rows=written)
    return written
