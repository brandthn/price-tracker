"""Smoke tests sur l'app FastAPI : healthz + OIDC bypass + run mocké."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa
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


def test_run_orchestrates_pipeline(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock chaque étape externe — on valide juste l'orchestration et la
    réponse JSON."""
    fake_raw_path = tmp_path / "raw.parquet"
    pa.parquet.write_table(  # type: ignore[attr-defined]
        pa.table(
            {
                "id": ["a"],
                "date": [date(2026, 5, 17)],
                "code": ["1"],
                "product_name": ["X"],
                "price": [1.0],
                "currency": ["EUR"],
                "location_id": [1],
                "location_osm_name": ["x"],
                "location_osm_address_country_code": ["FR"],
                "category_tag": [None],
                "kind": ["product"],
            }
        ),
        str(fake_raw_path),
    )

    from src import main as main_mod

    monkeypatch.setattr(main_mod, "download_snapshot", lambda **kwargs: fake_raw_path)
    monkeypatch.setattr(
        main_mod,
        "upload_snapshot",
        lambda **kwargs: f"gs://{kwargs['bucket']}/open-prices/dt={kwargs['snapshot_date']}/snapshot.parquet",
    )
    monkeypatch.setattr(main_mod, "load_and_merge", lambda **kwargs: 1)

    r = client.post("/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows_inserted"] == 1
    assert body["gcs_uri"].startswith("gs://price-tracker-prod-01-bronze/open-prices/dt=")
    assert "snapshot_date" in body
    assert isinstance(body["duration_s"], (int, float))
