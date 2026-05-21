"""FastAPI app — un seul endpoint métier (`POST /run`) + healthz."""

from __future__ import annotations

import os
import tempfile
import time
from datetime import UTC, date, datetime

from fastapi import Depends, FastAPI

from .auth import verify_oidc
from .bq import load_and_merge
from .config import get_settings
from .gcs import upload_snapshot
from .hf import download_snapshot
from .logging import configure_logging, get_logger
from .transform import normalize, read_parquet, write_parquet

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

app = FastAPI(
    title="prt-prod-worker-ingestion",
    docs_url=None,  # workers internes : pas de Swagger public
    redoc_url=None,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run")
def run(_oidc: dict = Depends(verify_oidc)) -> dict[str, object]:
    """Pipeline complet HF → GCS → BQ. Idempotent sur la journée courante."""
    t0 = time.monotonic()
    settings = get_settings()
    project_id = settings.google_cloud_project or _project_from_metadata()
    snapshot_date: date = datetime.now(UTC).date()

    logger.info(
        "run_start",
        project=project_id,
        bucket=settings.prt_bronze_bucket,
        dataset=settings.prt_bq_dataset_silver,
        table=settings.prt_bq_table_open_prices,
        snapshot_date=snapshot_date.isoformat(),
    )

    # 1) Download HF
    raw_path = download_snapshot(
        dataset=settings.prt_hf_dataset,
        filename=settings.prt_hf_filename,
        revision=settings.prt_hf_revision,
        token=settings.hf_token,
    )

    # 2) Transform → parquet local
    raw_table = read_parquet(str(raw_path))
    clean_table = normalize(
        raw_table,
        country_code_filter=settings.prt_filter_country_code or None,
    )

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        clean_path = tmp.name
    write_parquet(clean_table, clean_path)

    # 3) Upload GCS Bronze
    gcs_uri = upload_snapshot(
        project_id=project_id,
        bucket=settings.prt_bronze_bucket,
        snapshot_date=snapshot_date,
        local_path=clean_path,
    )

    # 4) Load + MERGE BQ Silver
    rows_inserted = load_and_merge(
        project_id=project_id,
        location="EU",
        dataset=settings.prt_bq_dataset_silver,
        table=settings.prt_bq_table_open_prices,
        gcs_uri=gcs_uri,
    )

    duration_s = round(time.monotonic() - t0, 2)
    logger.info(
        "run_done",
        snapshot_date=snapshot_date.isoformat(),
        rows_inserted=rows_inserted,
        duration_s=duration_s,
    )
    return {
        "snapshot_date": snapshot_date.isoformat(),
        "rows_inserted": rows_inserted,
        "duration_s": duration_s,
        "gcs_uri": gcs_uri,
    }


def _project_from_metadata() -> str:
    # Fallback si `GOOGLE_CLOUD_PROJECT` n'est pas injecté : interroger le
    # metadata server Cloud Run. Évite tout hardcoding du project_id.
    import google.auth

    _, project = google.auth.default()
    if not project:
        raise RuntimeError(
            "Cannot resolve GCP project_id. Set GOOGLE_CLOUD_PROJECT env var "
            "or run with ADC bound to a project."
        )
    return project
