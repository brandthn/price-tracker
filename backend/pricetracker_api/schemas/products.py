"""DTOs produits — toutes les colonnes OFF sont nullables (worker OFF rate-limité)."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    """Detail produit. Champs OFF nullables : worker OFF rate-limite et certains
    EAN absents de OFF (ligne quand meme presente, off_found=false)."""

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
    catalog: bool = Field(
        default=True,
        description="True si l'EAN existe dans Cloud SQL `products`. False = fiche "
        "« prix seulement » (EAN connu par ses relevés Silver, hors catalogue).",
    )
    source: str | None = None


class ProductSearchResult(BaseModel):
    items: list[ProductOut]
    total: int


class SubstituteOut(ProductOut):
    similarity: float = Field(
        description="Score cosine (1 = identique, 0 = orthogonal). Plus c'est haut, plus c'est proche."
    )


class PricePoint(BaseModel):
    """Médiane hebdomadaire des prix relevés pour un EAN (Silver open_prices_clean)."""

    week: datetime.date
    median_price_eur: float
    observations: int


class StorePrice(BaseModel):
    """Prix médian récent d'un EAN dans une enseigne — trié du moins cher au plus cher."""

    enseigne: str
    median_price_eur: float
    observations: int
    last_seen_week: datetime.date | None = None


class ProductPricesOut(BaseModel):
    """Historique + comparateur enseignes. series/by_store vides si EAN jamais
    releve dans Open Prices."""

    ean: str
    series: list[PricePoint] = Field(default_factory=list)
    by_store: list[StorePrice] = Field(default_factory=list)
    latest_median_eur: float | None = None
    pct_change_window: float | None = Field(
        default=None,
        description="Variation % entre la première et la dernière semaine de la série.",
    )
