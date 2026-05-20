"""Tests pour worker_off/off_api.py — parsing API Open Food Facts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from worker_off.off_api import summarize_product


def _make_payload(status: int = 1, product: dict | None = None) -> dict:
    return {"status": status, "product": product or {}}


# ── off_found ────────────────────────────────────────────────────────────────

def test_off_found_true_when_status_1():
    result = summarize_product(_make_payload(status=1))
    assert result["off_found"] is True


def test_off_found_false_when_status_0():
    result = summarize_product(_make_payload(status=0))
    assert result["off_found"] is False


def test_off_found_false_when_product_not_found():
    result = summarize_product({"status": 0, "product": {}})
    assert result["off_found"] is False


# ── name ────────────────────────────────────────────────────────────────────

def test_name_prefer_french():
    result = summarize_product(_make_payload(product={
        "product_name_fr": "Nutella",
        "product_name": "Nutella EN",
    }))
    assert result["name"] == "Nutella"


def test_name_fallback_to_product_name():
    result = summarize_product(_make_payload(product={
        "product_name": "Coca-Cola"
    }))
    assert result["name"] == "Coca-Cola"


def test_name_none_when_absent():
    result = summarize_product(_make_payload(product={}))
    assert result["name"] is None


# ── brand ────────────────────────────────────────────────────────────────────

def test_brand_single():
    result = summarize_product(_make_payload(product={"brands": "Danone"}))
    assert result["brand"] == "Danone"


def test_brand_takes_first_of_multiple():
    result = summarize_product(_make_payload(product={"brands": "Nestlé, KitKat, Rowntree's"}))
    assert result["brand"] == "Nestlé"


def test_brand_none_when_absent():
    result = summarize_product(_make_payload(product={}))
    assert result["brand"] is None


# ── catégories ───────────────────────────────────────────────────────────────

def test_categories_extracted():
    result = summarize_product(_make_payload(product={
        "categories_tags": ["en:dairy", "fr:yaourts", "fr:yaourts-nature"]
    }))
    assert result["category_l1"] is not None
    assert result["category_l2"] is not None
    assert result["category_l3"] is not None


def test_categories_none_when_absent():
    result = summarize_product(_make_payload(product={}))
    assert result["category_l1"] is None
    assert result["category_l2"] is None
    assert result["category_l3"] is None


def test_categories_partial():
    result = summarize_product(_make_payload(product={
        "categories_tags": ["en:dairy"]
    }))
    assert result["category_l1"] is not None
    assert result["category_l2"] is None


# ── nutriscore / nova / ecoscore ─────────────────────────────────────────────

def test_nutriscore_extracted():
    result = summarize_product(_make_payload(product={"nutriscore_grade": "b"}))
    assert result["nutriscore"] == "B"


def test_nova_extracted():
    result = summarize_product(_make_payload(product={"nova_group": 3}))
    assert result["nova"] == "3"


def test_ecoscore_extracted():
    result = summarize_product(_make_payload(product={"ecoscore_grade": "a"}))
    assert result["ecoscore"] == "A"


def test_scores_none_when_absent():
    result = summarize_product(_make_payload(product={}))
    assert result["nutriscore"] is None
    assert result["nova"] is None
    assert result["ecoscore"] is None


# ── image_url ────────────────────────────────────────────────────────────────

def test_image_url_extracted():
    result = summarize_product(_make_payload(product={
        "image_front_url": "https://images.openfoodfacts.org/img/3017620422003.jpg"
    }))
    assert "openfoodfacts" in result["image_url"]


def test_image_url_none_when_absent():
    result = summarize_product(_make_payload(product={}))
    assert result["image_url"] is None


# ── raw_json ─────────────────────────────────────────────────────────────────

def test_raw_json_is_string():
    result = summarize_product(_make_payload(status=1, product={"brands": "Danone"}))
    assert isinstance(result["raw_json"], str)
    assert "Danone" in result["raw_json"]
