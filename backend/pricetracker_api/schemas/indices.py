"""DTOs indices d'inflation (perso, régional, national) + observatoire."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


class IndexPoint(BaseModel):
    """Un point d'une série d'indice (typiquement par semaine ou mois)."""

    date: datetime.date
    value: float = Field(description="Indice base 100. 105.3 = +5.3% vs période de base.")
    sample_size: int | None = Field(
        default=None, description="Nombre de prix agrégés (qualité de l'indice)."
    )


class InflationIndexOut(BaseModel):
    scope: str = Field(description="personal | national | regional:{dept}")
    base_period: str | None = Field(
        default=None, description="ex: '2025-W01'. None si l'indice n'est pas encore calculé."
    )
    current: float | None = Field(default=None, description="Valeur la plus récente.")
    series: list[IndexPoint] = Field(default_factory=list)
    insee_comparison: float | None = Field(
        default=None,
        description="Indice INSEE COICOP correspondant à la même période, si dispo.",
    )


class RankingItem(BaseModel):
    ean: str | None
    produit_nom: str | None
    brand: str | None
    pct_change: float = Field(description="Variation en %. +10.5 = +10.5%.")
    price_eur_current: float | None
    price_eur_previous: float | None
    sample_size: int | None = None


class RankingsOut(BaseModel):
    period: str | None = None
    items: list[RankingItem] = Field(default_factory=list)


class MapDepartementValue(BaseModel):
    departement: str = Field(description="Code département FR (01-95, 2A, 2B, 971-976).")
    inflation_pct: float | None = None
    sample_size: int | None = None


class MapOut(BaseModel):
    period: str | None = None
    values: list[MapDepartementValue] = Field(default_factory=list)


class BrandStatsOut(BaseModel):
    """Stats agrégées par marque pour l'observatoire."""

    brand: str
    product_count: int
    avg_price_eur: float | None
    median_pct_change: float | None
    top_increases: list[RankingItem] = Field(default_factory=list)
