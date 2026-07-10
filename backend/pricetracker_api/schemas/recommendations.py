"""DTOs recommandations — « substitut moins cher » (reco Brique A, Étape 3).

Expose, pour les produits que l'utilisateur achète, le meilleur substitut
**moins cher au €/unité** et son **économie mensuelle** en euros réels.

Source des paires : cache `product_substitutions` (précalculé par le worker
`off`, kNN embeddings + accord catégoriel). Source du panier : agrégation
live des `prix_extraits` de l'utilisateur (mêmes tickets que `/me/basket`).
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
    """Un swap actionnable : « remplace `source` par `target`, économise
    `monthly_saving_eur` €/mois »."""

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
    """Liste des recommandations d'économies, triée par économie mensuelle desc.

    Panier vide ou aucun substitut moins cher → `items=[]`, `total=0`
    (jamais une erreur) : le frontend affiche « ajoutez un ticket »."""

    items: list[RecommendationItem] = Field(default_factory=list)
    total_monthly_saving_eur: float = 0.0
    count: int = 0
