"""Tests router products — focus sur le handling des NULL OFF.

Le worker OFF est rate-limité (15 req/min), donc le catalogue contient
des EAN avec `off_found=False` et name/brand/catégorie = NULL. Le router
doit renvoyer ces lignes en 200 sans planter.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pricetracker_api import bq


@pytest.fixture
def client() -> TestClient:
    import importlib

    from pricetracker_api import main as main_mod

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_get_product_with_off_found_true(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "ean": "3017620422003",
            "name": "Nutella",
            "brand": "Ferrero",
            "category_l1": "en:foods",
            "category_l2": "en:spreads",
            "category_l3": "en:sweet-spreads",
            "nutriscore": "E",
            "nova": "4",
            "ecoscore": "D",
            "image_url": "https://images.openfoodfacts.org/x.jpg",
            "off_found": True,
            "source": "openfoodfacts",
        }
    ]
    monkeypatch.setattr(bq, "query_dicts", lambda *a, **k: rows)
    r = client.get("/products/3017620422003")
    assert r.status_code == 200
    body = r.json()
    assert body["ean"] == "3017620422003"
    assert body["name"] == "Nutella"
    assert body["off_found"] is True


def test_get_product_null_tolerant_off_not_found(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EAN connu mais absent de OFF (404 OFF → off_found=False, tous champs NULL).
    Le backend doit renvoyer 200 avec les champs à None.
    """
    rows = [
        {
            "ean": "9999999999999",
            "name": None,
            "brand": None,
            "category_l1": None,
            "category_l2": None,
            "category_l3": None,
            "nutriscore": None,
            "nova": None,
            "ecoscore": None,
            "image_url": None,
            "off_found": False,
            "source": "openfoodfacts",
        }
    ]
    monkeypatch.setattr(bq, "query_dicts", lambda *a, **k: rows)
    r = client.get("/products/9999999999999")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["off_found"] is False
    assert body["name"] is None
    assert body["nutriscore"] is None


def test_get_product_404_when_unknown(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bq, "query_dicts", lambda *a, **k: [])
    r = client.get("/products/0000000000000")
    assert r.status_code == 404


def test_search_excludes_unenriched_eans(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La recherche full-text ne renvoie que les EAN enrichis (off_found=True)
    — sinon les EAN à NULL name/brand polluent les résultats (impossible
    à matcher de toute façon).
    """
    captured: dict = {}

    def _spy(sql, params=None):
        captured["sql"] = sql
        return [
            {
                "ean": "1",
                "name": "Lait demi-écrémé",
                "brand": "Lactel",
                "category_l1": None,
                "category_l2": None,
                "category_l3": None,
                "nutriscore": "B",
                "nova": None,
                "ecoscore": None,
                "image_url": None,
                "off_found": True,
                "source": "openfoodfacts",
            }
        ]

    monkeypatch.setattr(bq, "query_dicts", _spy)
    r = client.get("/products/search?q=lait")
    assert r.status_code == 200
    assert "off_found = TRUE" in captured["sql"]
    assert r.json()["items"][0]["name"] == "Lait demi-écrémé"
