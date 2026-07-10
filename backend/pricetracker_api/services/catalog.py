"""Résolution de noms produits contre le catalogue de référence Cloud SQL.

BigQuery expose les prix/EAN mais ne peut pas joindre Cloud SQL. Le catalogue de
référence (~14,5k EAN, noms/marques/images) vit dans Postgres `products` — PAS
dans le mini-miroir BQ `catalogue_produits`. On résout donc en deux temps : BQ
renvoie les EAN, puis un batch SQL complète nom/marque/image en Python.

Partagé par les routers `observatoire` et `enseignes` (un EAN sans fiche reste
affiché ACCOMPAGNÉ de son contexte, jamais nu → `in_catalog=false` côté contrat).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_products(
    session: AsyncSession, eans: list[str]
) -> dict[str, dict]:
    """Batch nom/marque/image contre Cloud SQL `products`.

    Renvoie `{ean: {name, brand, image_url}}` pour les seuls EAN présents au
    catalogue. Les EAN absents ne sont pas dans le dict → traités comme
    « produit non référencé » (accompagnés de leurs prix côté UI)."""
    if not eans:
        return {}
    result = await session.execute(
        text(
            "SELECT ean, name, brand, image_url FROM products WHERE ean = ANY(:eans)"
        ),
        {"eans": list(dict.fromkeys(eans))},
    )
    return {
        r["ean"]: {"name": r["name"], "brand": r["brand"], "image_url": r["image_url"]}
        for r in result.mappings().all()
    }
