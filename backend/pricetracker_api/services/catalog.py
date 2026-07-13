"""Resolution de noms produits contre le catalogue Cloud SQL.

BQ ne peut pas joindre Cloud SQL : BQ renvoie les EAN, puis un batch SQL complete
nom/marque/image depuis Postgres products (pas le miroir BQ catalogue_produits).
Partage par observatoire et enseignes ; EAN sans fiche = in_catalog=false.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_products(
    session: AsyncSession, eans: list[str]
) -> dict[str, dict]:
    # {ean: {name, brand, image_url}} pour les EAN presents au catalogue seulement
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
