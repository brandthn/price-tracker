"""FastAPI app worker alertes — POST /run produit un rapport JSON de hausses.

V1 simulation : pas de FCM push (frontend web only, pas de device tokens).
Le rapport est uploadé sur GCS sous `alerts/date=YYYY-MM-DD/report.json` et
loggé en stdout. Un endpoint backend Phase 11 pourra le servir aux clients.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Query

from .auth import verify_oidc
from .bq import AlertesConfig, fetch_top_anomalies, fetch_top_rankings
from .config import Settings, get_settings
from .gcs import upload_report
from .logging import configure_logging, get_logger

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

app = FastAPI(
    title="prt-prod-worker-alertes",
    docs_url=None,
    redoc_url=None,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _resolve_project(settings: Settings) -> str:
    if settings.google_cloud_project:
        return settings.google_cloud_project
    import google.auth

    _, project = google.auth.default()
    if not project:
        raise RuntimeError("Cannot resolve GCP project_id.")
    return project


def _build_config(settings: Settings, project_id: str) -> AlertesConfig:
    return AlertesConfig(
        project_id=project_id,
        dataset_gold=settings.prt_bq_dataset_gold,
        table_rankings=settings.prt_bq_table_rankings,
        table_anomalies=settings.prt_bq_table_anomalies,
        location=settings.prt_bq_location,
        top_rankings=settings.prt_alertes_top_rankings,
        top_anomalies=settings.prt_alertes_top_anomalies,
        min_pct_change=settings.prt_alertes_min_pct_change,
        lookback_weeks=settings.prt_alertes_lookback_weeks,
    )


@app.post("/run")
async def run(
    _oidc: dict = Depends(verify_oidc),
    run_date: str | None = Query(
        default=None,
        description="Date de référence ISO YYYY-MM-DD. Défaut : UTC today.",
    ),
) -> dict[str, object]:
    t0 = time.monotonic()
    settings = get_settings()
    project_id = _resolve_project(settings)
    effective_run_date = run_date or datetime.now(UTC).date().isoformat()
    cfg = _build_config(settings, project_id)

    logger.info(
        "run_start",
        project=project_id,
        run_date=effective_run_date,
        bucket=settings.prt_alerts_bucket or "(none — log only)",
    )

    rankings, anomalies = await asyncio.gather(
        asyncio.to_thread(fetch_top_rankings, cfg, effective_run_date),
        asyncio.to_thread(fetch_top_anomalies, cfg, effective_run_date),
    )

    payload = {
        "worker": "prt-prod-worker-alertes",
        "version": "v1-simulation",
        "run_date": effective_run_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "thresholds": {
            "min_pct_change": cfg.min_pct_change,
            "top_rankings": cfg.top_rankings,
            "top_anomalies": cfg.top_anomalies,
            "lookback_weeks": cfg.lookback_weeks,
        },
        "rankings": rankings,
        "anomalies": anomalies,
        "counts": {
            "rankings": len(rankings),
            "anomalies": len(anomalies),
        },
    }

    uri: str | None = None
    if settings.prt_alerts_bucket:
        uri = await asyncio.to_thread(
            upload_report,
            bucket=settings.prt_alerts_bucket,
            prefix=settings.prt_alerts_prefix,
            run_date=effective_run_date,
            payload=payload,
        )

    duration_s = round(time.monotonic() - t0, 2)
    logger.info(
        "run_done",
        duration_s=duration_s,
        run_date=effective_run_date,
        rankings_count=len(rankings),
        anomalies_count=len(anomalies),
        report_uri=uri,
    )

    return {
        "run_date": effective_run_date,
        "duration_s": duration_s,
        "rankings_count": len(rankings),
        "anomalies_count": len(anomalies),
        "report_uri": uri,
    }
