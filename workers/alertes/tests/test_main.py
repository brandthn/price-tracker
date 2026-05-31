"""Smoke tests app FastAPI worker alertes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from pricetracker_alertes.main import app

    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_run_returns_counts_no_bucket(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans bucket configuré, le worker log seulement et n'upload pas."""
    from pricetracker_alertes import main as main_mod

    monkeypatch.setattr(main_mod, "fetch_top_rankings", lambda cfg, run_date: [
        {"reference_week": "2026-05-26", "product_code": "3017620429484", "pct_change": 0.12}
    ])
    monkeypatch.setattr(main_mod, "fetch_top_anomalies", lambda cfg, run_date: [])

    # Track upload calls
    upload_called: dict[str, object] = {}

    def fake_upload(**kwargs):
        upload_called.update(kwargs)
        return "gs://fake/report.json"

    monkeypatch.setattr(main_mod, "upload_report", fake_upload)

    r = client.post("/run?run_date=2026-05-26")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_date"] == "2026-05-26"
    assert body["rankings_count"] == 1
    assert body["anomalies_count"] == 0
    # Bucket vide → pas d'upload, report_uri None
    assert body["report_uri"] is None
    assert upload_called == {}


def test_run_uploads_when_bucket_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRT_ALERTS_BUCKET", "price-tracker-test-bronze")

    from pricetracker_alertes import main as main_mod

    monkeypatch.setattr(main_mod, "fetch_top_rankings", lambda cfg, run_date: [])
    monkeypatch.setattr(main_mod, "fetch_top_anomalies", lambda cfg, run_date: [
        {"week_start_date": "2026-05-19", "product_code": "X", "z_score": -3.5}
    ])

    captured: dict[str, object] = {}

    def fake_upload(**kwargs):
        captured.update(kwargs)
        return "gs://price-tracker-test-bronze/alerts/date=2026-05-26/report.json"

    monkeypatch.setattr(main_mod, "upload_report", fake_upload)

    r = client.post("/run?run_date=2026-05-26")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_uri"] == "gs://price-tracker-test-bronze/alerts/date=2026-05-26/report.json"
    assert captured["bucket"] == "price-tracker-test-bronze"
    assert captured["prefix"] == "alerts"
    assert captured["run_date"] == "2026-05-26"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["counts"]["anomalies"] == 1
    assert payload["version"] == "v1-simulation"
