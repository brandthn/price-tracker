"""Tests observatoire — robustesse aux tables Gold vides (worker indices pas passe)."""

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


def test_rankings_returns_empty_when_gold_table_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BQ leve -> query_dicts_safe renvoie [], endpoint reste 200 items=[]
    def _raise(*_a, **_k):
        raise RuntimeError("Not found: Table rankings_produits")

    monkeypatch.setattr(bq, "query_dicts", _raise)
    r = client.get("/observatoire/rankings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert body["period"] is None


def test_rankings_with_data(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "ean": "111",
            "produit_nom": "Beurre",
            "brand": "Président",
            "pct_change": 12.5,
            "price_eur_current": 2.50,
            "price_eur_previous": 2.22,
            "sample_size": 42,
            "period": "2026-W18",
        }
    ]
    monkeypatch.setattr(bq, "query_dicts", lambda *a, **k: rows)
    r = client.get("/observatoire/rankings")
    assert r.status_code == 200
    body = r.json()
    assert body["period"] == "2026-W18"
    assert body["items"][0]["pct_change"] == 12.5


def test_map_returns_empty_when_gold_table_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*_a, **_k):
        raise RuntimeError("BQ access denied")

    monkeypatch.setattr(bq, "query_dicts", _raise)
    r = client.get("/observatoire/map")
    assert r.status_code == 200
    body = r.json()
    assert body["values"] == []


def test_indices_national_empty_safe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bq, "query_dicts", lambda *a, **k: [])
    r = client.get("/indices/national")
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "national"
    assert body["series"] == []
    assert body["current"] is None
