"""Smoke tests app FastAPI worker indices."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from pricetracker_indices.main import app

    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_run_invokes_refresh(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le endpoint /run appelle refresh_gold_tables et renvoie les counts."""
    from pricetracker_indices import main as main_mod

    fake_counts = {
        "aggregats_enseignes": 42,
        "indices_inflation": 42,
        "rankings_produits": 7,
        "anomalies_detected": 3,
    }

    def fake_refresh(cfg, run_date):
        return fake_counts

    monkeypatch.setattr(main_mod, "refresh_gold_tables", fake_refresh)

    r = client.post("/run?run_date=2026-05-26")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_date"] == "2026-05-26"
    assert body["rows"] == fake_counts
    assert isinstance(body["duration_s"], int | float)


def test_run_default_run_date(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans param `run_date`, le worker utilise la date UTC du jour."""
    from pricetracker_indices import main as main_mod

    captured: dict[str, object] = {}

    def fake_refresh(cfg, run_date):
        captured["run_date"] = run_date
        return {"aggregats_enseignes": 0, "indices_inflation": 0, "rankings_produits": 0, "anomalies_detected": 0}

    monkeypatch.setattr(main_mod, "refresh_gold_tables", fake_refresh)

    r = client.post("/run")
    assert r.status_code == 200
    # Date UTC du jour au format ISO
    assert isinstance(captured["run_date"], str)
    assert len(captured["run_date"]) == 10  # YYYY-MM-DD
