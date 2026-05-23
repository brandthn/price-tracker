"""Tests des enrichissements Silver : enseigne, ville, EAN, discount, IQR."""

from __future__ import annotations

import pytest

from pricetracker_ingestion.enrichments import (
    check_discount_coherence,
    flag_iqr_outliers,
    normalize_store_brand,
    standardize_city,
    validate_ean,
)


# ---------------------------------------------------------------------------
# normalize_store_brand
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Lidl, 12 Rue de la Paix, Paris, France", "Lidl"),
        ("E.Leclerc Drive, Z.A. La Confluence", "E.Leclerc"),
        ("E Leclerc, ...", "E.Leclerc"),
        ("Carrefour Market, Lyon", "Carrefour Market"),
        ("Carrefour City, Marseille", "Carrefour City"),
        ("Carrefour Hypermarché, Bordeaux", "Carrefour"),
        ("Auchan Supermarché, Lille", "Auchan Supermarché"),
        ("Auchan, Nantes", "Auchan"),
        ("Intermarche, Nice", "Intermarché"),
        ("Lidl", "Lidl"),
        ("Monop' Daily, Paris", "Monoprix"),
        ("Géant Casino, Toulouse", "Géant Casino"),
        ("Bio C'Bon, Paris", "Bio C'Bon"),  # inconnu → fallback premier segment
        (None, None),
        ("", None),
    ],
)
def test_normalize_store_brand(raw: str | None, expected: str | None) -> None:
    assert normalize_store_brand(raw) == expected


# ---------------------------------------------------------------------------
# standardize_city
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("PARIS", "Paris"),
        ("paris", "Paris"),
        ("Paris 17e Arrondissement", "Paris"),
        ("Lyon 7e Arrondissement", "Lyon"),
        ("Marseille 13e", "Marseille"),
        ("Échirolles", "Échirolles"),
        ("  Bordeaux  ", "Bordeaux"),
        (None, None),
        ("", None),
        ("  ", None),
    ],
)
def test_standardize_city(raw: str | None, expected: str | None) -> None:
    assert standardize_city(raw) == expected


# ---------------------------------------------------------------------------
# validate_ean
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,ok",
    [
        ("3017620422003", True),  # Nutella, checksum valide
        ("8076809513753", True),  # Barilla, checksum valide
        ("9999999999999", False),  # 13 chiffres mais checksum incorrect
        ("3017620422004", False),  # off by one
        ("12345678", False),  # 8 chiffres mais checksum incorrect
        ("123456", False),  # mauvaise longueur
        ("3017620422003X", False),  # caractère non numérique
        ("", False),
        (None, False),
    ],
)
def test_validate_ean(code: str | None, ok: bool) -> None:
    result, details = validate_ean(code)
    assert result is ok
    if not ok:
        assert details is not None


# ---------------------------------------------------------------------------
# check_discount_coherence
# ---------------------------------------------------------------------------


def test_discount_not_marked_is_coherent() -> None:
    row = {"price_eur": 2.0, "price_without_discount_eur": 3.0, "price_is_discounted": False}
    assert check_discount_coherence(row) == (True, None)


def test_discount_marked_but_no_full_price_is_tolerated() -> None:
    row = {"price_eur": 2.0, "price_without_discount_eur": None, "price_is_discounted": True}
    assert check_discount_coherence(row) == (True, None)


def test_discount_inverted_is_rejected() -> None:
    row = {"price_eur": 3.0, "price_without_discount_eur": 2.0, "price_is_discounted": True}
    ok, details = check_discount_coherence(row)
    assert ok is False
    assert details is not None


def test_discount_too_large_is_rejected() -> None:
    """Une remise > 95% est considérée comme une erreur de saisie."""
    row = {"price_eur": 0.05, "price_without_discount_eur": 5.0, "price_is_discounted": True}
    ok, _ = check_discount_coherence(row)
    assert ok is False


def test_discount_reasonable_passes() -> None:
    row = {"price_eur": 2.0, "price_without_discount_eur": 3.0, "price_is_discounted": True}
    assert check_discount_coherence(row) == (True, None)


# ---------------------------------------------------------------------------
# flag_iqr_outliers
# ---------------------------------------------------------------------------


def test_iqr_no_outliers_in_uniform_prices() -> None:
    rows = [{"product_code": "EAN1", "price_eur": p} for p in [2.0] * 10]
    flag_iqr_outliers(rows)
    assert all(r["iqr_outlier"] is False for r in rows)


def test_iqr_flags_obvious_outlier() -> None:
    prices = [2.0, 2.1, 2.0, 1.9, 2.05, 2.1, 999.0]  # 999 = aberrant
    rows = [{"product_code": "EAN1", "price_eur": p} for p in prices]
    flag_iqr_outliers(rows)
    outliers = [r["iqr_outlier"] for r in rows]
    assert outliers[-1] is True
    assert sum(outliers) == 1


def test_iqr_skips_low_volume_eans() -> None:
    """< 5 observations → pas de flag (impossible de calculer un quartile fiable)."""
    rows = [{"product_code": "EAN1", "price_eur": p} for p in [2.0, 2.0, 999.0]]
    flag_iqr_outliers(rows)
    assert all(r["iqr_outlier"] is False for r in rows)


def test_iqr_independent_per_product() -> None:
    rows = (
        [{"product_code": "EAN1", "price_eur": p} for p in [2.0] * 10]
        + [{"product_code": "EAN2", "price_eur": p} for p in [100.0] * 10]
    )
    flag_iqr_outliers(rows)
    # Aucun outlier (uniformes) malgré la différence de prix entre les 2 EAN.
    assert all(r["iqr_outlier"] is False for r in rows)


def test_iqr_empty_input_safe() -> None:
    rows: list[dict] = []
    flag_iqr_outliers(rows)
    assert rows == []
