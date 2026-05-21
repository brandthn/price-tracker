"""Parser + comportements HTTP du client OFF (mocks via pytest-httpx)."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from src.off_client import OFFClient, _to_off_product

_BASE = "https://world.openfoodfacts.org"
_UA = "pricetracker-test/0.1"


@pytest.fixture
def client() -> OFFClient:
    # rate-limit très haut → ne pas ralentir les tests
    return OFFClient(
        base_url=_BASE,
        user_agent=_UA,
        rate_limit_rpm=6000,
        timeout_s=5.0,
        max_retries=3,
    )


def test_parse_found_product() -> None:
    payload = {
        "status": 1,
        "product": {
            "product_name_fr": "Nutella",
            "brands": "Ferrero, Nutella",
            "categories_tags": ["en:foods", "en:spreads", "en:sweet-spreads", "en:hazelnut-spreads"],
            "nutriscore_grade": "e",
            "nova_group": 4,
            "ecoscore_grade": "d",
            "image_front_url": "https://example.com/nutella.jpg",
        },
    }
    p = _to_off_product("3017620422003", payload)
    assert p.found is True
    assert p.name == "Nutella"
    assert p.brand == "Ferrero"  # premier brand uniquement
    assert p.category_l1 == "en:foods"
    assert p.category_l3 == "en:hazelnut-spreads"
    assert p.nutriscore == "E"
    assert p.nova == "4"
    assert p.ecoscore == "D"
    assert p.image_url == "https://example.com/nutella.jpg"


def test_parse_not_found() -> None:
    p = _to_off_product("999", {"status": 0, "status_verbose": "no match"})
    assert p.found is False
    assert p.name is None
    assert p.brand is None
    assert p.category_l3 is None


def test_embedding_text_falls_back_to_ean() -> None:
    p = _to_off_product("1234", {"status": 0})
    # not found → name/brand/cat tous None → embedding_text == ean
    assert p.embedding_text == "1234"


def test_embedding_text_joins_known_parts() -> None:
    payload = {
        "status": 1,
        "product": {
            "product_name": "Lait demi-écrémé",
            "brands": "Lactel",
            "categories_tags": ["en:dairies", "en:milks", "en:semi-skimmed-milks"],
        },
    }
    p = _to_off_product("3033710065608", payload)
    assert "Lait demi-écrémé" in p.embedding_text
    assert "Lactel" in p.embedding_text
    assert "en:semi-skimmed-milks" in p.embedding_text


async def test_fetch_product_http_404_returns_not_found(
    client: OFFClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/api/v2/product/0000.json?fields={_fields_param()}",
        status_code=404,
    )
    p = await client.fetch_product("0000")
    assert p.found is False
    assert p.ean == "0000"


async def test_fetch_product_retries_on_5xx_then_succeeds(
    client: OFFClient, httpx_mock: HTTPXMock
) -> None:
    url = f"{_BASE}/api/v2/product/3017620422003.json?fields={_fields_param()}"
    httpx_mock.add_response(url=url, status_code=503)
    httpx_mock.add_response(url=url, status_code=503)
    httpx_mock.add_response(
        url=url,
        status_code=200,
        json={
            "status": 1,
            "product": {
                "product_name_fr": "Nutella",
                "brands": "Ferrero",
                "categories_tags": ["en:foods", "en:spreads"],
            },
        },
    )
    p = await client.fetch_product("3017620422003")
    assert p.found is True
    assert p.name == "Nutella"


def _fields_param() -> str:
    # Reflète l'ordre des champs `_FIELDS` du module — pytest-httpx matche
    # l'URL exacte query string incluse.
    from src import off_client

    return off_client._FIELDS  # noqa: SLF001
