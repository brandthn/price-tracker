"""
Worker alertes — simulation V1 (guide §5 worker 4).

- Attend le signal `worker_indices`.
- Lit les anomalies détectées sur la fenêtre récente.
- Produit un rapport JSON (logs + fichier local ou objet GCS optionnel).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from loguru import logger

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from google.cloud import bigquery, storage  # noqa: E402

from shared.config import load_settings, utc_today_iso  # noqa: E402
from shared.monitoring import (  # noqa: E402
    STATUS_FAILED,
    STATUS_SUCCESS,
    build_worker_signal,
    utcnow_iso,
    write_signal_to_bucket,
)
from shared.orchestration import wait_for_upstream_worker  # noqa: E402
from shared.signals import write_local_signal  # noqa: E402


def _execution_date() -> str:
    return os.getenv("EXECUTION_DATE") or utc_today_iso()


def _persist_signal(settings, execution_date: str, payload: Dict[str, Any]) -> str:
    if settings.use_gcp and settings.gcs_signals_bucket:
        client = storage.Client(project=settings.project_id)
        return write_signal_to_bucket(
            storage_client=client,
            bucket_name=settings.gcs_signals_bucket,
            execution_date=execution_date,
            worker_name="worker_alertes",
            signal_payload=payload,
        )
    path = write_local_signal(Path("./artifacts"), execution_date, "worker_alertes", payload)
    return str(path)


def _fetch_anomalies(client: bigquery.Client, fq: str, run_date: str, limit: int = 500) -> List[Dict[str, Any]]:
    sql = f"""
    SELECT week_start_date, product_code, store_brand, median_price_eur, z_score
    FROM `{fq}.anomaliesdetected`
    WHERE week_start_date >= DATE_SUB(DATE(@run_date), INTERVAL 8 WEEK)
    ORDER BY ABS(z_score) DESC
    LIMIT {limit}
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_date", "DATE", run_date)]
    )
    return [dict(r) for r in client.query(sql, job_config=job_config).result()]


def run() -> None:
    load_dotenv()
    settings = load_settings()
    execution_date = _execution_date()
    started_at = utcnow_iso()
    metrics: Dict[str, Any] = {}

    try:
        wait_for_upstream_worker(settings, execution_date, "worker_indices")

        report: Dict[str, Any] = {
            "execution_date": execution_date,
            "worker": "worker_alertes",
            "message": "Rapport de simulation V1 — aucune notification utilisateur envoyée.",
            "anomalies_sample": [],
        }

        if settings.use_gcp:
            client = bigquery.Client(project=settings.project_id)
            fq = f"{settings.project_id}.{settings.bq_dataset}"
            rows = _fetch_anomalies(client, fq, execution_date)
            report["anomalies_sample"] = rows
            metrics["anomalies_in_report"] = len(rows)
        else:
            metrics["skipped_bigquery"] = True

        logger.info(json.dumps(report, ensure_ascii=False, indent=2, default=str))

        report_path = Path("./artifacts") / f"alertes_simulation_{execution_date}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        metrics["report_path"] = str(report_path)

        if settings.use_gcp and settings.gcs_artifacts_bucket:
            sc = storage.Client(project=settings.project_id)
            blob = sc.bucket(settings.gcs_artifacts_bucket).blob(
                f"alertes-sim/date={execution_date}/report.json"
            )
            blob.upload_from_string(
                json.dumps(report, ensure_ascii=False, indent=2, default=str),
                content_type="application/json",
            )
            metrics["gcs_report_uri"] = f"gs://{settings.gcs_artifacts_bucket}/{blob.name}"

        finished_at = utcnow_iso()
        payload = build_worker_signal(
            worker_name="worker_alertes",
            execution_date=execution_date,
            status=STATUS_SUCCESS,
            started_at=started_at,
            finished_at=finished_at,
            metrics=metrics,
            quality_gates=[],
        )
        dest = _persist_signal(settings, execution_date, payload)
        logger.success(f"worker_alertes terminé — signal : {dest}")

    except Exception as exc:  # noqa: BLE001
        logger.exception("worker_alertes en échec")
        finished_at = utcnow_iso()
        payload = build_worker_signal(
            worker_name="worker_alertes",
            execution_date=execution_date,
            status=STATUS_FAILED,
            started_at=started_at,
            finished_at=finished_at,
            metrics=metrics,
            quality_gates=[],
            error_message=str(exc),
        )
        _persist_signal(settings, execution_date, payload)
        raise SystemExit(1) from exc


def main() -> None:
    run()


if __name__ == "__main__":
    main()
