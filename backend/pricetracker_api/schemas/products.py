"""DTOs produits — toutes les colonnes OFF sont nullables (worker OFF rate-limité)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    """Détail produit. Tous les champs OFF sont NULL-tolerant : le worker OFF
    est rate-limité (15 req/min) et certains EAN sont absents de OFF — la
    ligne existe quand même en SQL/BQ avec `off_found=false`.
    """

    ean: str
    name: str | None = None
    brand: str | None = None
    category_l1: str | None = None
    category_l2: str | None = None
    category_l3: str | None = None
    nutriscore: str | None = None
    nova: str | None = None
    ecoscore: str | None = None
    image_url: str | None = None
    off_found: bool = False
    source: str | None = None


class ProductSearchResult(BaseModel):
    items: list[ProductOut]
    total: int


class SubstituteOut(ProductOut):
    similarity: float = Field(
        description="Score cosine (1 = identique, 0 = orthogonal). Plus c'est haut, plus c'est proche."
    )
