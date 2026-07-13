"""DTOs recommandations — substitut moins cher (Brique A, Etape 3).

Meilleur substitut moins cher au €/unite + economie mensuelle. Paires depuis
product_substitutions (worker off, kNN embeddings + accord categoriel) ; panier
depuis agregation live des prix_extraits (memes tickets que /me/basket).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RecoProductRef(BaseModel):
    """Fiche compacte d'un produit dans une reco (source achetée ou substitut)."""

    ean: str
    name: str | None = None
    brand: str | None = None
    image_url: str | None = None
    price_per_unit: float = Field(
        description="Prix médian au €/unité (kg ou L), jamais le prix paquet."
    )


class RecommendationItem(BaseModel):
    """Un swap : remplace source par target, economise monthly_saving_eur/mois."""

    source: RecoProductRef
    target: RecoProductRef
    unit: str = Field(description="Unité de comparaison : 'kg' ou 'L'.")
    tier: int = Field(description="1 « sûr », 2 « probable » (Tier 3 non exposé).")
    score: float = Field(description="Confiance ∈ [0,1] (catégorie + embedding borné).")
    saving_per_unit: float = Field(description="Économie au €/unité (source - cible).")
    saving_pct: float = Field(description="Économie en pourcentage (0-100).")
    monthly_packs: float = Field(
        description="Nombre de paquets/mois consommés (achats 6 mois / 6)."
    )
    monthly_saving_eur: float = Field(
        description="Économie mensuelle en euros = saving_per_unit x taille pack x paquets/mois."
    )


class RecommendationsOut(BaseModel):
    """Recommandations triees par economie mensuelle desc. Panier vide ou aucun
    substitut moins cher -> items=[], total=0 (jamais d'erreur)."""

    items: list[RecommendationItem] = Field(default_factory=list)
    total_monthly_saving_eur: float = 0.0
    count: int = 0
