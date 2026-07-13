"""Scoring des paires substitut→produit 
Ne compare que des produits moins chers à l'unité et de même dimension (kg↔kg, L↔L)
"""

from __future__ import annotations

from dataclasses import dataclass


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass(frozen=True)
class ScoreWeights:

    w_cat: float = 0.75  # poids catégorie (dominant)
    w_emb: float = 0.50  # plafond embedding : emb seul ne dépasse jamais ça
    cos_floor: float = 0.35  # plancher cosinus (gate candidat + base de normalisation)
    cos_ref: float = 0.75  # cosinus au-delà duquel emb_norm sature à 1
    tier1_cat: float = 0.80  # cat_agreement min pour Tier 1 « sûr »
    tier2_cat: float = 0.30  # cat_agreement min pour Tier 2 « probable »


def category_agreement(
    source_l3: str | None,
    target_l3: str | None,
    source_tags: list[str] | None,
    target_tags: list[str] | None,
) -> float:
    if source_l3 and target_l3 and source_l3 == target_l3:
        return 1.0
    if not source_tags or not target_tags:
        return 0.0
    shared = set(source_tags) & set(target_tags)
    if not shared:
        return 0.0
    depth = len(source_tags)
    deepest_pos = max(i + 1 for i, t in enumerate(source_tags) if t in shared)
    return deepest_pos / depth


def score_and_tier(cosine: float, cat_agree: float, w: ScoreWeights) -> tuple[float, int]:
    emb_norm = _clamp01((cosine - w.cos_floor) / (w.cos_ref - w.cos_floor))
    confidence = min(1.0, w.w_cat * cat_agree + w.w_emb * emb_norm)
    if cat_agree >= w.tier1_cat:
        tier = 1
    elif cat_agree >= w.tier2_cat:
        tier = 2
    else:
        tier = 3
    return confidence, tier


@dataclass(frozen=True)
class RawCandidate:

    target_ean: str
    cosine: float
    cat_agree: float
    target_ppu: float  # prix €/unité canonique (kg ou L)
    target_obs: int  # nb d'observations de prix (confiance du prix cible)
    target_brand: str | None


@dataclass(frozen=True)
class RankedSubstitute:
    target_ean: str
    tier: int
    score: float
    cosine: float
    cat_agreement: float
    target_ppu: float
    saving_per_unit: float
    saving_pct: float
    target_obs: int


def rank_substitutes(
    source_ppu: float,
    candidates: list[RawCandidate],
    *,
    w: ScoreWeights,
    top_n: int,
    max_per_brand: int,
) -> list[RankedSubstitute]:
    scored: list[tuple[float, float, str, RankedSubstitute]] = []
    for c in candidates:
        if not (c.target_ppu < source_ppu):  # doit être strictement moins cher au €/unité
            continue
        if c.cosine < w.cos_floor:
            continue
        confidence, tier = score_and_tier(c.cosine, c.cat_agree, w)
        saving = source_ppu - c.target_ppu
        saving_pct = saving / source_ppu if source_ppu > 0 else 0.0
        scored.append(
            (
                confidence,
                saving_pct,
                (c.target_brand or "").strip().lower(),
                RankedSubstitute(
                    target_ean=c.target_ean,
                    tier=tier,
                    score=round(confidence, 4),
                    cosine=round(c.cosine, 4),
                    cat_agreement=round(c.cat_agree, 4),
                    target_ppu=round(c.target_ppu, 4),
                    saving_per_unit=round(saving, 4),
                    saving_pct=round(saving_pct, 4),
                    target_obs=c.target_obs,
                ),
            )
        )

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

    kept: list[RankedSubstitute] = []
    per_brand: dict[str, int] = {}
    for _conf, _spct, brand, sub in scored:
        if brand:
            if per_brand.get(brand, 0) >= max_per_brand:
                continue
            per_brand[brand] = per_brand.get(brand, 0) + 1
        kept.append(sub)
        if len(kept) >= top_n:
            break
    return kept
