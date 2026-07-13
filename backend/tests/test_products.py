"""Tests router products — detail + recherche sur Cloud SQL products.

EAN off_found=False (absents de OFF) doivent sortir en 200, champs NULL.
Pas de testcontainers en CI : get_session override par une fausse session.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def _make_product(**overrides) -> SimpleNamespace:
    base = dict(
        ean="3017620422003",
        name="Nutella",
        brand="Ferrero",
        category_l1="en:foods",
        category_l2="en:spreads",
        category_l3="en:sweet-spreads",
        nutriscore="E",
        nova="4",
        ecoscore="D",
        image_url="https://images.openfoodfacts.org/x.jpg",
        off_found=True,
        source="openfoodfacts",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeMappings:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def all(self) -> list[dict]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeSession:
    # get = detail produit, execute = recherche
    def __init__(self, product=None, search_rows: list[dict] | None = None):
        self._product = product
        self._search_rows = search_rows or []
        self.last_params: dict | None = None
        self.last_sql: str | None = None

    async def get(self, _model, _pk):
        return self._product

    async def execute(self, stmt, params=None):
        self.last_sql = str(stmt)
        self.last_params = params
        return _FakeResult(self._search_rows)


@pytest.fixture
def make_client():
    def _build(session: _FakeSession) -> TestClient:
        import importlib

        from pricetracker_api import main as main_mod
        from pricetracker_api.db import get_session

        importlib.reload(main_mod)
        main_mod.app.dependency_overrides[get_session] = lambda: session
        return TestClient(main_mod.app)

    return _build


def test_get_product_with_off_found_true(make_client) -> None:
    client = make_client(_FakeSession(product=_make_product()))
    r = client.get("/products/3017620422003")
    assert r.status_code == 200
    body = r.json()
    assert body["ean"] == "3017620422003"
    assert body["name"] == "Nutella"
    assert body["off_found"] is True


def test_get_product_null_tolerant_off_not_found(make_client) -> None:
    # off_found=False, champs NULL -> 200
    product = _make_product(
        ean="9999999999999",
        name=None,
        brand=None,
        category_l1=None,
        category_l2=None,
        category_l3=None,
        nutriscore=None,
        nova=None,
        ecoscore=None,
        image_url=None,
        off_found=False,
    )
    client = make_client(_FakeSession(product=product))
    r = client.get("/products/9999999999999")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["off_found"] is False
    assert body["name"] is None
    assert body["nutriscore"] is None


def test_get_product_404_when_unknown(make_client) -> None:
    client = make_client(_FakeSession(product=None))
    r = client.get("/products/0000000000000")
    assert r.status_code == 404


def test_search_excludes_unenriched_eans(make_client) -> None:
    # recherche = off_found=True only
    session = _FakeSession(
        search_rows=[
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
    )
    client = make_client(session)
    r = client.get("/products/search?q=lait")
    assert r.status_code == 200
    assert "off_found = TRUE" in session.last_sql
    assert r.json()["items"][0]["name"] == "Lait demi-écrémé"


def test_search_escapes_like_wildcards(make_client) -> None:
    # %/_ traites litteralement, pas comme jokers SQL
    session = _FakeSession(search_rows=[])
    client = make_client(session)
    r = client.get("/products/search?q=50%25_lait")
    assert r.status_code == 200
    assert session.last_params is not None
    assert session.last_params["pattern"] == "%50\\%\\_lait%"
