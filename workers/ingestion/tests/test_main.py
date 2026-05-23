"""Smoke tests sur l'app FastAPI : healthz + OIDC bypass + run mocké."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from pricetracker_ingestion.main import app

    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_run_orchestrates_pipeline(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock chaque étape externe (HF, GCS, BQ) — on valide juste que l'app
    appelle les bonnes fonctions et renvoie la réponse JSON attendue."""
    fake_raw_path = tmp_path / "raw.parquet"
    pq.write_table(
        pa.table(
            {
                "id": ["a"],
                "date": [date(2026, 5, 17)],
                "product_code": ["3017620422003"],  # Nutella, EAN valide
                "price": [3.49],
                "currency": ["EUR"],
                "location_osm_address_country": ["France"],
                "proof_type": ["RECEIPT"],
                "location_osm_display_name": ["Lidl, Paris"],
            }
        ),
        str(fake_raw_path),
    )

    from pricetracker_ingestion import main as main_mod

    monkeypatch.setattr(main_mod, "download_snapshot", lambda **kwargs: fake_raw_path)
    monkeypatch.setattr(
        main_mod,
        "upload_snapshot",
        lambda **kwargs: f"gs://{kwargs['bucket']}/open-prices/dt={kwargs['snapshot_date']}/snapshot.parquet",
    )
    monkeypatch.setattr(main_mod, "load_and_merge_clean", lambda **kwargs: 1)
    monkeypatch.setattr(main_mod, "load_rejections", lambda **kwargs: 0)

    r = client.post("/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows_merged_clean"] == 1
    assert body["rows_loaded_rejections"] == 0
    assert body["gcs_uri"].startswith("gs://price-tracker-prod-01-bronze/open-prices/dt=")
    assert "pipeline_run_date" in body
    assert isinstance(body["duration_s"], int | float)
    # Metrics propagées : on vérifie au moins la présence des clés.
    metrics = body["metrics"]
    assert metrics["rows_input"] == 1
    assert metrics["rows_clean"] == 1
    assert metrics["rows_rejected"] == 0
