"""Scoring substituts : catégorie = high-signal, embedding = borné (Étape 2)."""

from __future__ import annotations

import pytest

from pricetracker_off.substitutions import (
    RawCandidate,
    ScoreWeights,
    category_agreement,
    rank_substitutes,
    score_and_tier,
)

W = ScoreWeights()

_NUTELLA = ["en:foods", "en:spreads", "en:sweet-spreads", "en:chocolate-spreads", "en:hazelnut-spreads"]


def test_cat_agreement_same_l3_is_max() -> None:
    assert category_agreement("en:hazelnut-spreads", "en:hazelnut-spreads", None, None) == 1.0


def test_cat_agreement_deep_shared_tag_high() -> None:
    # l3 différents mais partagent en:chocolate-spreads (position 4/5 = profond)
    other = ["en:foods", "en:spreads", "en:sweet-spreads", "en:chocolate-spreads", "en:cocoa-spreads"]
    a = category_agreement("en:hazelnut-spreads", "en:cocoa-spreads", _NUTELLA, other)
    assert a == pytest.approx(4 / 5)  # tag commun le plus profond = position 4 sur 5


def test_cat_agreement_shallow_shared_tag_low() -> None:
    # ne partagent que la racine en:foods (position 1/5)
    biscuit = ["en:foods", "en:snacks", "en:sweet-snacks", "en:biscuits-and-cakes", "en:biscuits"]
    a = category_agreement("en:hazelnut-spreads", "en:biscuits", _NUTELLA, biscuit)
    assert a == pytest.approx(1 / 5)


def test_cat_agreement_no_overlap_zero() -> None:
    shampoo = ["en:non-food-products", "en:cosmetics", "en:hair-products", "en:shampoos"]
    assert category_agreement("en:hazelnut-spreads", "en:shampoos", _NUTELLA, shampoo) == 0.0


def test_embedding_alone_is_capped() -> None:
    # cosinus parfait, aucune catégorie → plafonné à w_emb (0.50), Tier 3
    score, tier = score_and_tier(cosine=1.0, cat_agree=0.0, w=W)
    assert score == pytest.approx(0.50)
    assert tier == 3


def test_same_deep_category_reaches_quasi_max() -> None:
    # même catégorie profonde + embedding modéré → quasi-max, Tier 1
    score, tier = score_and_tier(cosine=0.60, cat_agree=1.0, w=W)
    assert score > 0.85
    assert tier == 1


def test_biscuit_nutella_is_demoted() -> None:
    # LE cas de Brandon : cosinus très fort (marque commune) mais catégorie éloignée
    # → reste Tier 3, score sous un vrai substitut de même catégorie.
    biscuit_score, biscuit_tier = score_and_tier(cosine=0.90, cat_agree=0.2, w=W)
    real_sub_score, real_sub_tier = score_and_tier(cosine=0.72, cat_agree=1.0, w=W)
    assert biscuit_tier == 3
    assert real_sub_tier == 1
    assert real_sub_score > biscuit_score


def test_rank_filters_more_expensive_per_unit() -> None:
    # source à 8 €/kg ; un candidat à 9.9 €/kg (paquet moins cher mais + cher/kg) exclu
    cands = [
        RawCandidate("A", cosine=0.8, cat_agree=1.0, target_ppu=9.9, target_obs=5, target_brand="X"),
        RawCandidate("B", cosine=0.7, cat_agree=1.0, target_ppu=5.0, target_obs=5, target_brand="Y"),
    ]
    out = rank_substitutes(8.0, cands, w=W, top_n=5, max_per_brand=2)
    assert [s.target_ean for s in out] == ["B"]
    assert out[0].saving_per_unit == pytest.approx(3.0)


def test_rank_brand_diversity_cap() -> None:
    cands = [
        RawCandidate("A1", 0.9, 1.0, 5.0, 5, "Carrefour"),
        RawCandidate("A2", 0.85, 1.0, 4.5, 5, "Carrefour"),
        RawCandidate("A3", 0.8, 1.0, 4.0, 5, "Carrefour"),
        RawCandidate("B1", 0.7, 1.0, 6.0, 5, "Lidl"),
    ]
    out = rank_substitutes(8.0, cands, w=W, top_n=5, max_per_brand=1)
    brands_kept = [s.target_ean for s in out]
    assert "B1" in brands_kept  # l'autre marque remonte malgré un score plus bas
    assert sum(1 for e in brands_kept if e.startswith("A")) == 1  # une seule Carrefour


def test_build_rows_end_to_end() -> None:
    """Pipeline complet (jointure prix + €/unité + score) sur données synthétiques."""
    from pricetracker_off.compute_substitutions import _build_rows
    from pricetracker_off.config import get_settings

    spread = ["en:foods", "en:spreads", "en:sweet-spreads", "en:chocolate-spreads", "en:hazelnut-spreads"]
    products = {
        "S":  {"name": "Nutella", "brand": "Ferrero", "category_l3": "en:hazelnut-spreads",
               "categories_tags": spread, "quantity_value": 0.75, "quantity_unit": "kg"},
        "C1": {"name": "Pâte choco 1er prix", "brand": "Carrefour", "category_l3": "en:hazelnut-spreads",
               "categories_tags": spread, "quantity_value": 0.40, "quantity_unit": "kg"},
        "C2": {"name": "Pâte choco chère", "brand": "Bonne Maman", "category_l3": "en:hazelnut-spreads",
               "categories_tags": spread, "quantity_value": 0.40, "quantity_unit": "kg"},
        "B":  {"name": "Biscuit Nutella", "brand": "Ferrero", "category_l3": "en:biscuits",
               "categories_tags": ["en:foods", "en:snacks", "en:biscuits-and-cakes", "en:biscuits"],
               "quantity_value": 0.30, "quantity_unit": "kg"},
    }
    prices = {  # (median_eur, obs)
        "S":  (6.0, 10),   # 8.0 €/kg
        "C1": (2.0, 5),    # 5.0 €/kg  → moins cher ✓
        "C2": (5.0, 5),    # 12.5 €/kg → plus cher/kg ✗ (paquet moins cher, piège Maty)
        "B":  (1.5, 5),    # 5.0 €/kg  → moins cher mais catégorie éloignée
    }
    pairs = [("S", "C1", 0.72), ("S", "C2", 0.80), ("S", "B", 0.90)]

    rows, sample, tiers = _build_rows(products, prices, pairs, get_settings())
    targets = [r[1] for r in rows]
    assert "C2" not in targets                     # exclu : plus cher au €/kg
    assert targets[0] == "C1"                       # meilleur score en tête (même catégorie)
    assert set(targets) == {"C1", "B"}
    tier_by_target = {r[1]: r[2] for r in rows}
    assert tier_by_target["C1"] == 1                # même l3 → Tier 1
    assert tier_by_target["B"] == 3                 # cosinus fort mais catégorie éloignée → Tier 3
    assert tiers[1] >= 1 and tiers[3] >= 1
    assert sample and sample[0]["src"] == "Nutella"
