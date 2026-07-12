"""Schemas Pydantic v2 — endpoints /recommendations/*.

Conventions alignées sur schemas/products.py :
- `model_config = ConfigDict(from_attributes=True)`
- snake_case, pas d'alias
- float arrondis à 2 décimales max dans les réponses
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# GET /recommendations/product/{ean}
# ---------------------------------------------------------------------------


class ProductAlternative(BaseModel):
    """Une alternative moins chère à un produit source."""

    model_config = ConfigDict(from_attributes=True)

    ean: str
    name: str | None = None
    brand: str | None = None
    nutriscore: str | None = None
    image_url: str | None = None

    avg_price: float | None = Field(None, description="Prix moyen constaté (€)")
    saving_avg: float | None = Field(None, description="Économie absolue vs source (€)")
    saving_pct: float | None = Field(None, description="Économie en % vs source")
    score: float = Field(description="Score composite [0.0 – 1.0]")
    similarity: float | None = Field(None, description="Similarité sémantique cosine")


class ProductRecommendationsResponse(BaseModel):
    """Réponse GET /recommendations/product/{ean}."""

    source_ean: str
    source_name: str | None = None
    source_avg_price: float | None = None
    alternatives: list[ProductAlternative] = Field(
        description="Top alternatives triées par score DESC (max 3)"
    )


# ---------------------------------------------------------------------------
# GET /recommendations/user/{user_id}
# ---------------------------------------------------------------------------


class UserProductRecommendation(BaseModel):
    """Recommandation pour un produit acheté par l'utilisateur."""

    model_config = ConfigDict(from_attributes=True)

    purchased_ean: str
    purchased_name: str | None = None
    purchased_avg_price: float | None = None

    alternative_ean: str
    alternative_name: str | None = None
    alternative_avg_price: float | None = None
    alternative_nutriscore: str | None = None
    alternative_image_url: str | None = None

    saving_avg: float | None = Field(None, description="Économie par achat (€)")
    saving_pct: float | None = Field(None, description="Économie en %")
    score: float


class UserRecommendationsResponse(BaseModel):
    """Réponse GET /recommendations/user/{user_id}."""

    user_id: str
    potential_monthly_savings: float | None = Field(
        None,
        description=(
            "Économie potentielle mensuelle estimée (€) "
            "= somme des saving_avg sur les achats du dernier mois"
        ),
    )
    recommendations: list[UserProductRecommendation] = Field(
        description="Une recommandation par produit distinct acheté, triée par saving_avg DESC"
    )
