"""Smoke tests app FastAPI worker OFF."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from src.main import app

    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_run_empty_eans_short_circuits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si discover_eans_to_enrich renvoie [], le run ne tente ni OFF ni
    Vertex ni pg — juste un payload zéro."""
    from src import main as main_mod

    monkeypatch.setattr(main_mod, "discover_eans_to_enrich", lambda **kwargs: [])

    r = client.post("/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enqueued"] == 0
    assert body["off_found"] == 0
    assert body["rows_upserted_bq"] == 0
    assert body["rows_upserted_pg"] == 0
    assert isinstance(body["duration_s"], (int, float))
