"""Unit tests for the shared alias normaliser (pure, no DB)."""

from __future__ import annotations

from pricetracker_matching.normalize import (
    enseigne_candidates,
    enseigne_key,
    normalize_label,
)


def test_normalize_label_case_accents_punct():
    assert normalize_label("PAIN COMPLET !!") == "pain complet"
    assert normalize_label("Café Éthiopie 250g") == normalize_label("CAFE ETHIOPIE 250G")
    assert normalize_label("COCA-COLA 1.5L") == "coca cola 1 5l"


def test_normalize_label_keeps_digits_no_lossy_prefix_drop():
    # Unlike the catalogue normaliser, leading tokens are NOT dropped, so these
    # stay distinct.
    assert normalize_label("500G BEURRE") == "500g beurre"
    assert normalize_label("250G BEURRE") == "250g beurre"
    assert normalize_label("500G BEURRE") != normalize_label("250G BEURRE")


def test_normalize_label_empty_and_none():
    assert normalize_label("") == ""
    assert normalize_label(None) == ""
    assert normalize_label("   ") == ""


def test_enseigne_key_matches_sql_fold_shape():
    # lower + fixed accent map + collapse non-alnum runs to single space + trim.
    assert enseigne_key("CARREFOUR MARKET") == "carrefour market"
    assert enseigne_key("Intermarché") == "intermarche"
    assert enseigne_key("Carrefour-Market") == "carrefour market"
    assert enseigne_key("  Super   U  ") == "super u"


def test_enseigne_candidates_include_brand_root():
    exact, folded = enseigne_candidates("CARREFOUR MARKET")
    assert "" in exact                # wildcard always eligible
    assert "CARREFOUR MARKET" in exact
    assert "carrefour market" in folded
    assert "carrefour" in folded      # brand root reaches shorter catalogue enseignes


def test_enseigne_candidates_short_root_not_added():
    # Single-letter root ("u") is too generic → excluded.
    _exact, folded = enseigne_candidates("super u")
    assert "super u" in folded
    assert "u" not in folded


def test_enseigne_candidates_empty():
    exact, folded = enseigne_candidates(None)
    assert exact == [""]
    assert folded == [""]
