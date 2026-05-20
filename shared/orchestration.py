"""Attente du signal amont (GCS ou fichiers locaux `artifacts/`)."""

from __future__ import annotations

import time
from pathlib import Path

from google.cloud import storage

from shared.config import PipelineSettings
from shared.monitoring import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    UpstreamSignalFailedError,
    UpstreamSignalTimeoutError,
    read_signal_from_bucket,
    wait_for_upstream_signal,
)
from shared.signals import read_local_signal


def wait_for_upstream_worker(
    settings: PipelineSettings,
    execution_date: str,
    upstream_worker_name: str,
    local_artifacts_dir: Path | None = None,
) -> dict:
    """Bloque jusqu’à SUCCESS du worker amont ; lève si FAILED ou timeout."""
    if settings.use_gcp and settings.gcs_signals_bucket:
        client = storage.Client(project=settings.project_id)
        return wait_for_upstream_signal(
            storage_client=client,
            bucket_name=settings.gcs_signals_bucket,
            execution_date=execution_date,
            upstream_worker_name=upstream_worker_name,
            max_wait_seconds=settings.signal_max_wait_seconds,
            poll_interval_seconds=settings.signal_poll_interval_seconds,
        )

    base = local_artifacts_dir or Path("./artifacts")
    waited = 0
    while waited <= settings.signal_max_wait_seconds:
        sig = read_local_signal(base, execution_date, upstream_worker_name)
        if sig is not None:
            status = sig.get("status")
            if status == STATUS_SUCCESS:
                return sig
            if status == STATUS_FAILED:
                raise UpstreamSignalFailedError(
                    f"Upstream {upstream_worker_name} failed: {sig.get('error_message')}"
                )
        time.sleep(settings.signal_poll_interval_seconds)
        waited += settings.signal_poll_interval_seconds

    raise UpstreamSignalTimeoutError(
        f"Timeout waiting for local signal {upstream_worker_name}"
    )


def read_upstream_if_present(
    settings: PipelineSettings,
    execution_date: str,
    upstream_worker_name: str,
    local_artifacts_dir: Path | None = None,
) -> dict | None:
    """Lecture non bloquante (utilitaire tests / debug)."""
    if settings.use_gcp and settings.gcs_signals_bucket:
        client = storage.Client(project=settings.project_id)
        return read_signal_from_bucket(
            storage_client=client,
            bucket_name=settings.gcs_signals_bucket,
            execution_date=execution_date,
            worker_name=upstream_worker_name,
        )
    base = local_artifacts_dir or Path("./artifacts")
    return read_local_signal(base, execution_date, upstream_worker_name)
