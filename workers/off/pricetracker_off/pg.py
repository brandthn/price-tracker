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
from decimal import Decimal
from typing import Any

import asyncpg

from .logging import get_logger
from .off_client import OFFProduct
from .quantity import normalize_quantity

logger = get_logger(__name__)


def _vector_literal(vec: Sequence[float]) -> str:
    # pgvector accepte '[1.0,2.0,...]' en text — convertit côté SQL via
    # le cast `::vector(768)`. Float repr Python est suffisamment précis.
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"


def _quantity_numeric(value: float | None) -> Decimal | None:
    """float canonique (kg/L) → Decimal pour la colonne NUMERIC (asyncpg exige
    un Decimal, pas un float, sur un type `numeric`). None passe tel quel."""
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
    """INSERT … ON CONFLICT (ean) DO UPDATE. Retourne le nombre de rows écrits.

    `embeddings[i]` correspond à `products[i]` ; `None` autorisé (cas `off_found=false`
    où l'embedding n'a pas été calculé).

    `source` trace la provenance : `openfoodfacts` (worker API 1-par-1, défaut),
    `openfoodfacts_dump` (chargement bulk depuis le dump OFF via load_artifact).
    Distingue les deux voies d'acquisition, sinon indistinguables en base.
    """
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
    """Re-embed « embedding-only » (vague 2) : `UPDATE products SET embedding = …
    WHERE ean = …`, SANS toucher aucune autre colonne.

    Garde-fou (§3 handoff) : ne régresse jamais les données curées (name/brand/
    image_url/scores/source, dont l'import Maty). Ne touche pas non plus
    `enriched_at` (ce n'est pas une ré-enrichissement du produit, juste un
    rafraîchissement du vecteur). Idempotent.

    - Ignore les entrées sans embedding (tombstones) : rien à mettre à jour.
    - Un EAN absent de `products` → l'UPDATE ne matche 0 ligne (no-op sûr).

    Retourne {'candidates': N, 'updated': M} où `updated` = lignes réellement
    modifiées (M ≤ N si des EAN ne sont pas en base).
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
    """Backfill des colonnes socle reco (Étapes 1+2) sur les produits DÉJÀ en base :
    `UPDATE products SET quantity_raw/quantity_value/quantity_unit/categories_tags
    = … WHERE ean = …`, SANS toucher aucune autre colonne.

    Même garde-fou que `update_embeddings` : zéro régression sur les données
    curées (name/brand/image_url/scores/embedding/source, dont l'import Maty).
    Idempotent. Sert à alimenter les ~12 k produits déjà en base (le worker
    quotidien, lui, écrit ces colonnes à l'`upsert` des nouveaux EAN).

    - quantité : `(value, unit)` via `normalize_quantity` (g→kg, ml→L) ; sans unité
      propre → value/unit NULL (exclu du €/unité), `quantity_raw` garde le texte OFF ;
    - `categories_tags` : chemin OFF complet (pour la profondeur de préfixe commun,
      tier catégorie §4). NULL si absent.

    Retourne {'candidates': N, 'updated': M} — M ≤ N si des EAN ne sont pas en base.
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
