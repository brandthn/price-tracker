from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from pricetracker_off.embedding_text import build_embedding_text
from pricetracker_off.off_client import OFFClient, _to_off_product

_BASE = "https://world.openfoodfacts.org"
_UA = "pricetracker-test/0.1"


@pytest.fixture
def client() -> OFFClient:
    # rate-limit très haut + backoff zéro → ne pas ralentir les tests
    return OFFClient(
        base_url=_BASE,
        user_agent=_UA,
        rate_limit_rpm=6000,
        timeout_s=5.0,
        max_retries=3,
        retry_wait_min_s=0.0,
        retry_wait_max_s=0.0,
        retry_wait_multiplier=0.0,
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
    # champs texte-embedding (non persistés) — pris tels quels de l'API
    assert p.categories_tags == ["en:foods", "en:spreads", "en:sweet-spreads", "en:hazelnut-spreads"]


def test_parse_found_product_carries_embedding_fields() -> None:
    payload = {
        "status": 1,
        "product": {
            "product_name_fr": "Nesquik Cacao",
            "generic_name_fr": "Poudre cacaotée",
            "brands": "Nestlé, Nesquik",
            "categories_tags": ["en:beverages", "en:cocoa-and-chocolate-powders"],
            "labels_tags": ["en:no-gluten", "en:green-dot"],
            "quantity": "1 kg",
        },
    }
    p = _to_off_product("3033710065967", payload)
    assert p.brand == "Nestlé"  # première marque
    assert p.generic_name == "Poudre cacaotée"
    assert p.labels_tags == ["en:no-gluten", "en:green-dot"]
    assert p.quantity == "1 kg"


def test_parse_carries_normalized_quantity_fields() -> None:
    """Socle unité : product_quantity (numérique, en g/ml chez OFF) +
    product_quantity_unit sont récupérés bruts (le cast/normalisation a lieu à
    l'écriture via quantity.normalize_quantity). OFF renvoie parfois un nombre."""
    payload = {
        "status": 1,
        "product": {
            "product_name_fr": "Coca-Cola",
            "brands": "Coca-Cola",
            "quantity": "1,5 L",
            "product_quantity": 1500,  # nombre côté API
            "product_quantity_unit": "ml",
        },
    }
    p = _to_off_product("5449000000996", payload)
    assert p.quantity == "1,5 L"  # texte libre → quantity_raw
    assert p.product_quantity == "1500"  # stocké en texte (parité dump VARCHAR)
    assert p.product_quantity_unit == "ml"


def test_parse_missing_quantity_fields_default_none() -> None:
    payload = {"status": 1, "product": {"product_name_fr": "Sel"}}
    p = _to_off_product("0000000000000", payload)
    assert p.product_quantity is None
    assert p.product_quantity_unit is None


def test_parse_not_found() -> None:
    p = _to_off_product("999", {"status": 0, "status_verbose": "no match"})
    assert p.found is False
    assert p.name is None
    assert p.brand is None
    assert p.category_l3 is None


def test_embedding_text_falls_back_to_ean() -> None:
    p = _to_off_product("1234", {"status": 0})
    # not found → name/brand/cat tous None → texte == ean
    assert build_embedding_text(p) == "1234"


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
    txt = build_embedding_text(p)
    assert "Lait demi-écrémé" in txt
    assert "marque Lactel" in txt
    # formule balanced : catégories nettoyées (préfixe en: retiré, tirets->espaces)
    # et hiérarchie COMPLÈTE (pas seulement l3)
    assert "catégorie dairies > milks > semi skimmed milks" in txt
    assert "en:" not in txt


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
    from pricetracker_off import off_client

    return off_client._FIELDS
