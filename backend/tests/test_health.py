"""Smoke tests : healthz + openapi expose + CORS."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    # Force la reconstruction de l'app après le clean_env de conftest
    # (les settings sont lus au build).
    import importlib

    from pricetracker_api import main as main_mod

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_enabled_by_default(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["info"]["title"] == "PriceTracker API"
    # Vérifie quelques routes critiques pour ne pas merger un build cassé.
    paths = spec["paths"]
    assert "/healthz" in paths
    assert "/tickets/upload-url" in paths
    assert "/products/search" in paths
    assert "/products/{ean}" in paths
    assert "/observatoire/rankings" in paths
    assert "/stats/brand/{brand}" in paths


def test_openapi_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    monkeypatch.setenv("PRT_OPENAPI_ENABLED", "false")
    from pricetracker_api import config

    config.reset_settings_cache()

    from pricetracker_api import main as main_mod

    importlib.reload(main_mod)
    client = TestClient(main_mod.app)
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
    # /healthz reste exposé.
    assert client.get("/healthz").status_code == 200
