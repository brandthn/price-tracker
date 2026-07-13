"""DTOs comparateur d'enseignes (indice de cherte relative, matched-basket).

Pour chaque produit releve dans >=2 enseignes : ratio prix median enseigne /
mediane inter-enseignes ; indice = mediane des ratios x100 (100 = median, <100
moins chere). Comparaison produit par produit, donc pas biaise par le mix.
Evolution des prix par enseigne non exposee (decision 2026-07-09, biais assortiment).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EnseigneSummary(BaseModel):
    """Une ligne du comparateur."""

    enseigne: str
    cherte_index: float | None = Field(
        default=None,
        description="Indice de cherté relative (base 100). None si la couverture "
        "est insuffisante (< min_matched produits comparables).",
    )
    matched_products: int = Field(
        description="Nombre de produits comparables (relevés aussi ailleurs). "
        "C'est le signal de confiance de l'indice."
    )
    observations: int | None = Field(
        default=None,
        description="Nombre de relevés de prix sur les produits comparés (contexte).",
    )


class EnseignesOut(BaseModel):
    window_weeks: int = Field(description="Fenêtre d'analyse en semaines.")
    min_matched: int = Field(
        description="Seuil de produits comparables sous lequel l'indice n'est pas affiché."
    )
    reference_index: float = Field(
        default=100.0, description="Repère : 100 = niveau médian inter-enseignes."
    )
    items: list[EnseigneSummary] = Field(default_factory=list)


class EnseigneProductRank(BaseModel):
    """Un produit sur lequel une enseigne se situe (moins / plus chère)."""

    ean: str | None
    produit_nom: str | None
    brand: str | None
    image_url: str | None = None
    in_catalog: bool = Field(
        default=True,
        description="False = produit connu par ses seuls prix (affiché accompagné, jamais nu).",
    )
    price_eur: float | None = Field(
        default=None, description="Prix médian de l'enseigne sur ce produit."
    )
    ref_price_eur: float | None = Field(
        default=None, description="Médiane inter-enseignes du produit (référence)."
    )
    delta_pct: float = Field(
        description="Écart au prix de référence, en %. −12.0 = 12% moins cher que la médiane."
    )


class EnseigneDetailOut(BaseModel):
    enseigne: str
    tracked: bool = Field(
        description="False = enseigne non suivie (aucun relevé) → écran dédié, pas un 404."
    )
    cherte_index: float | None = None
    matched_products: int = 0
    observations: int | None = None
    window_weeks: int
    min_matched: int
    cheaper: list[EnseigneProductRank] = Field(
        default_factory=list,
        description="Produits où l'enseigne est la moins chère vs la médiane.",
    )
    dearer: list[EnseigneProductRank] = Field(
        default_factory=list,
        description="Produits où l'enseigne est la plus chère vs la médiane.",
    )
