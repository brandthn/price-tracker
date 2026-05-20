"""Tests pour local_pipeline/silver_enrichments.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local_pipeline.silver_enrichments import (
    check_discount_coherence,
    compute_price_bounds,
    flag_suspicious_prices,
    normalize_store_brand,
    standardize_city,
    validate_ean,
)


# ── validate_ean ──────────────────────────────────────────────────────────────

def test_ean13_valid():
    ok, reason = validate_ean("3560070283484")
    assert ok is True
    assert reason is None


def test_ean13_bad_checksum():
    ok, reason = validate_ean("3560070283485")  # dernier chiffre modifié
    assert ok is False
    assert "checksum" in reason.lower()


def test_ean8_valid():
    ok, reason = validate_ean("20012548")
    assert ok is True


def test_ean_non_numeric():
    ok, reason = validate_ean("ABCDEF12345")
    assert ok is False


def test_ean_wrong_length():
    ok, reason = validate_ean("12345")
    assert ok is False
    assert "longueur" in reason.lower()


def test_ean_none():
    ok, reason = validate_ean(None)
    assert ok is False


def test_ean_empty():
    ok, reason = validate_ean("")
    assert ok is False


# ── normalize_store_brand ────────────────────────────────────────────────────

def test_normalize_leclerc():
    raw = "Centre Commercial E.Leclerc, Rue de la Paix, 75001, Paris, France"
    assert normalize_store_brand(raw) == "E.Leclerc"


def test_normalize_carrefour_market():
    raw = "Carrefour Market, 37 Rue de Lyon, Paris 12e, France"
    assert normalize_store_brand(raw) == "Carrefour Market"


def test_normalize_carrefour_city():
    raw = "Carrefour City Montparnasse, Paris, France"
    assert normalize_store_brand(raw) == "Carrefour City"


def test_normalize_carrefour_generique():
    raw = "Carrefour Hypermarché, Bordeaux, France"
    assert normalize_store_brand(raw) == "Carrefour"


def test_normalize_intermarche():
    raw = "Intermarché, Rue des Grands Vents, Aulnay, France"
    assert normalize_store_brand(raw) == "Intermarché"


def test_normalize_lidl():
    raw = "Lidl, Rue Victor Hugo, Lyon, France"
    assert normalize_store_brand(raw) == "Lidl"


def test_normalize_inconnu_retourne_raw():
    raw = "Épicerie du Coin, 12 Rue des Fleurs"
    result = normalize_store_brand(raw)
    assert result == raw


def test_normalize_none():
    assert normalize_store_brand(None) is None


# ── standardize_city ─────────────────────────────────────────────────────────

def test_standardize_paris_majuscule():
    assert standardize_city("PARIS") == "Paris"


def test_standardize_paris_arrondissement():
    assert standardize_city("Paris 17e Arrondissement") == "Paris"


def test_standardize_lyon():
    assert standardize_city("LYON 7e") == "Lyon"


def test_standardize_marseille_minuscule():
    assert standardize_city("marseille") == "Marseille"


def test_standardize_accent_preserve():
    assert standardize_city("Échirolles") == "Échirolles"


def test_standardize_none():
    assert standardize_city(None) is None


# ── check_discount_coherence ─────────────────────────────────────────────────

def test_discount_coherent():
    row = {
        "price_eur": 2.0,
        "price_without_discount_eur": 3.0,
        "price_is_discounted": True,
    }
    ok, reason = check_discount_coherence(row)
    assert ok is True
    assert reason is None


def test_discount_incoherent_price_greater():
    row = {
        "price_eur": 3.0,
        "price_without_discount_eur": 2.0,
        "price_is_discounted": True,
    }
    ok, reason = check_discount_coherence(row)
    assert ok is False
    assert "remise" in reason.lower() or "≥" in reason


def test_discount_too_high():
    row = {
        "price_eur": 0.05,
        "price_without_discount_eur": 10.0,
        "price_is_discounted": True,
    }
    ok, reason = check_discount_coherence(row)
    assert ok is False
    assert "%" in reason or "remise" in reason.lower()


def test_no_discount_flag_skips_check():
    row = {
        "price_eur": 5.0,
        "price_without_discount_eur": 2.0,
        "price_is_discounted": False,
    }
    ok, reason = check_discount_coherence(row)
    assert ok is True


def test_discount_flag_without_original_price():
    row = {
        "price_eur": 2.0,
        "price_without_discount_eur": None,
        "price_is_discounted": True,
    }
    ok, reason = check_discount_coherence(row)
    assert ok is True


# ── compute_price_bounds + flag_suspicious_prices ────────────────────────────

def _make_rows(product_code: str, prices: list) -> list:
    return [
        {"product_code": product_code, "price_eur": p, "id": str(i)}
        for i, p in enumerate(prices)
    ]


def test_compute_bounds_needs_min_samples():
    rows = _make_rows("EAN1", [1.0, 2.0, 3.0])  # seulement 3 < min_samples=5
    bounds = compute_price_bounds(rows, iqr_factor=3.0, min_samples=5)
    assert "EAN1" not in bounds


def test_compute_bounds_calcule_correctement():
    prices = [1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1]
    rows = _make_rows("EAN2", prices)
    bounds = compute_price_bounds(rows, iqr_factor=3.0, min_samples=5)
    assert "EAN2" in bounds
    lo, hi = bounds["EAN2"]
    assert lo < 1.5
    assert hi > 2.1


def test_flag_suspicious_prices_detecte_aberrant():
    rows = _make_rows("EAN3", [2.0, 2.1, 2.0, 1.9, 2.05, 0.01])  # 0.01 aberrant
    bounds = compute_price_bounds(rows, iqr_factor=3.0, min_samples=5)
    clean, suspicious = flag_suspicious_prices(rows, bounds)
    suspicious_prices = [r["price_eur"] for r in suspicious]
    assert 0.01 in suspicious_prices


def test_flag_suspicious_prices_accepte_normal():
    rows = _make_rows("EAN4", [2.0, 2.1, 2.0, 1.9, 2.05, 2.03])
    bounds = compute_price_bounds(rows, iqr_factor=3.0, min_samples=5)
    clean, suspicious = flag_suspicious_prices(rows, bounds)
    assert len(suspicious) == 0
    assert len(clean) == 6


def test_flag_no_bounds_passe_tout():
    rows = _make_rows("EAN5", [1.0, 2.0, 3.0])  # pas de bornes calculées
    clean, suspicious = flag_suspicious_prices(rows, {})
    assert len(clean) == 3
    assert len(suspicious) == 0
