"""FastAPI app — un seul endpoint métier (`POST /run`) + healthz."""

from __future__ import annotations

import os
import tempfile
import time
from datetime import UTC, datetime

from fastapi import Depends, FastAPI

from .auth import verify_oidc
from .bq import load_and_merge_clean, load_rejections
from .cleaner import (
    DEFAULT_ALLOWED_CURRENCIES,
    DEFAULT_ALLOWED_PROOF_TYPES,
    CleanerConfig,
)
from .config import get_settings
from .gcs import upload_snapshot
from .hf import download_snapshot
from .logging import configure_logging, get_logger
from .transform import read_parquet, transform_open_prices, write_parquet

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
    """Pipeline complet HF → transform (clean + rejections) → GCS Bronze → BQ.

    Idempotent sur la journée courante : MERGE pour clean, TRUNCATE-partition
    pour rejections (cf. bq.py).
    """
    t0 = time.monotonic()
    settings = get_settings()
    project_id = settings.google_cloud_project or _project_from_metadata()
    run_date = datetime.now(UTC).date()

    logger.info(
        "run_start",
        project=project_id,
        bucket=settings.prt_bronze_bucket,
        dataset=settings.prt_bq_dataset_silver,
        table_clean=settings.prt_bq_table_open_prices,
        table_rejections=settings.prt_bq_table_rejections,
        pipeline_run_date=run_date.isoformat(),
        allowed_countries=sorted(settings.allowed_countries),
    )

    # 1) Download snapshot HF.
    raw_path = download_snapshot(
        dataset=settings.prt_hf_dataset,
        filename=settings.prt_hf_filename,
        revision=settings.prt_hf_revision,
        token=settings.hf_token,
    )

    # 2) Transform : raw → (clean, rejections, metrics).
    raw_table = read_parquet(str(raw_path))
    cleaner_config = CleanerConfig(
        allowed_countries=settings.allowed_countries,
        allowed_currencies=DEFAULT_ALLOWED_CURRENCIES,
        allowed_proof_types=DEFAULT_ALLOWED_PROOF_TYPES,
        reference_date=run_date,
    )
    clean_table, rejections_table, metrics = transform_open_prices(
        raw_table,
        pipeline_run_date=run_date,
        config=cleaner_config,
    )

    # 3) Archive clean en Bronze (l'archive raw HF n'a pas de valeur métier — le
    #    snapshot HF est lui-même immuable et adressable par date).
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        clean_path = tmp.name
    write_parquet(clean_table, clean_path)
    gcs_uri = upload_snapshot(
        project_id=project_id,
        bucket=settings.prt_bronze_bucket,
        snapshot_date=run_date,
        local_path=clean_path,
    )

    # 4) Load + MERGE BQ Silver (clean) depuis Bronze.
    rows_merged = load_and_merge_clean(
        project_id=project_id,
        location="EU",
        dataset=settings.prt_bq_dataset_silver,
        table=settings.prt_bq_table_open_prices,
        gcs_uri=gcs_uri,
    )

    # 5) Load rejections directement depuis pyarrow (WRITE_TRUNCATE partition).
    #    Pas d'archive Bronze : les rejections sont de la donnée d'audit, leur
    #    archivage long-terme dans GCS n'apporte rien de plus que la table BQ.
    rows_rejected = load_rejections(
        project_id=project_id,
        location="EU",
        dataset=settings.prt_bq_dataset_silver,
        table=settings.prt_bq_table_rejections,
        rejections=rejections_table,
        partition_day=run_date,
    )

    duration_s = round(time.monotonic() - t0, 2)
    logger.info(
        "run_done",
        pipeline_run_date=run_date.isoformat(),
        rows_merged_clean=rows_merged,
        rows_loaded_rejections=rows_rejected,
        duration_s=duration_s,
        **{f"metrics_{k}": v for k, v in metrics.items()},
    )
    return {
        "pipeline_run_date": run_date.isoformat(),
        "rows_merged_clean": rows_merged,
        "rows_loaded_rejections": rows_rejected,
        "duration_s": duration_s,
        "gcs_uri": gcs_uri,
        "metrics": metrics,
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
