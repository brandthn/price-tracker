"""FastAPI app worker indices — POST /run recalcule les 4 tables Gold."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Query

from .auth import verify_oidc
from .bq import IndicesConfig, refresh_gold_tables
from .config import Settings, get_settings
from .logging import configure_logging, get_logger

configure_logging(level=os.environ.get("PRT_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

app = FastAPI(
    title="prt-prod-worker-indices",
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


def _build_config(settings: Settings, project_id: str) -> IndicesConfig:
    return IndicesConfig(
        project_id=project_id,
        dataset_silver=settings.prt_bq_dataset_silver,
        dataset_gold=settings.prt_bq_dataset_gold,
        table_open_prices=settings.prt_bq_table_open_prices,
        table_aggregats=settings.prt_bq_table_aggregats,
        table_indices=settings.prt_bq_table_indices,
        table_rankings=settings.prt_bq_table_rankings,
        table_anomalies=settings.prt_bq_table_anomalies,
        location=settings.prt_bq_location,
        min_observations=settings.prt_indices_min_observations,
        window_weeks_aggregats=settings.prt_indices_window_weeks_aggregats,
        window_weeks_rankings=settings.prt_indices_window_weeks_rankings,
        z_threshold=settings.prt_indices_z_threshold,
        top_n_rankings=settings.prt_indices_top_n_rankings,
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
        dataset_silver=cfg.dataset_silver,
        dataset_gold=cfg.dataset_gold,
        min_observations=cfg.min_observations,
        window_weeks_agg=cfg.window_weeks_aggregats,
        window_weeks_rk=cfg.window_weeks_rankings,
    )

    counts = await asyncio.to_thread(refresh_gold_tables, cfg, effective_run_date)

    duration_s = round(time.monotonic() - t0, 2)
    logger.info(
        "run_done",
        duration_s=duration_s,
        run_date=effective_run_date,
        **{f"rows_{k}": v for k, v in counts.items()},
    )
    return {
        "run_date": effective_run_date,
        "duration_s": duration_s,
        "rows": counts,
    }
