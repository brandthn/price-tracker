"""
Worker OFF — enrichissement catalogue Open Food Facts (guide §5 worker 2).

- Attend le signal `worker_ingestion` (GCS ou local).
- Liste les EAN présents dans `openpricesclean` mais absents de `catalogueproduits`.
- Interroge l’API OFF, insère les lignes dans BigQuery.
- Quality gate : taux de résolution (HTTP status=1) ≥ 80 %.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from loguru import logger

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKER_DIR = Path(__file__).resolve().parent
for _p in (_REPO_ROOT, _WORKER_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from google.cloud import bigquery, storage  # noqa: E402

from shared.bq_io import insert_rows_in_batches  # noqa: E402
from shared.bq_setup import ensure_dataset_and_silver_tables  # noqa: E402
from shared.config import load_settings, utc_today_iso  # noqa: E402
from shared.monitoring import (  # noqa: E402
    STATUS_FAILED,
    STATUS_SUCCESS,
    QualityGateError,
    build_worker_signal,
    evaluate_min_threshold,
    raise_if_quality_gates_failed,
    utcnow_iso,
    write_signal_to_bucket,
)
from shared.orchestration import wait_for_upstream_worker  # noqa: E402
from shared.signals import write_local_signal  # noqa: E402

from off_api import fetch_product_json, summarize_product  # noqa: E402


def _execution_date() -> str:
    return os.getenv("EXECUTION_DATE") or utc_today_iso()


def _persist_signal(settings, execution_date: str, payload: Dict[str, Any]) -> str:
    if settings.use_gcp and settings.gcs_signals_bucket:
        client = storage.Client(project=settings.project_id)
        return write_signal_to_bucket(
            storage_client=client,
            bucket_name=settings.gcs_signals_bucket,
            execution_date=execution_date,
            worker_name="worker_off",
            signal_payload=payload,
        )
    path = write_local_signal(Path("./artifacts"), execution_date, "worker_off", payload)
    return str(path)


def _list_eans_to_enrich(client: bigquery.Client, fq_dataset: str, run_date: str, limit: int | None) -> List[str]:
    lim = f"LIMIT {int(limit)}" if limit else ""
    sql = f"""
    WITH recent AS (
      SELECT DISTINCT TRIM(product_code) AS ean
      FROM `{fq_dataset}.openpricesclean`
      WHERE pipeline_run_date >= DATE_SUB(DATE(@run_date), INTERVAL 30 DAY)
        AND product_code IS NOT NULL
        AND TRIM(product_code) != ''
    )
    SELECT r.ean
    FROM recent r
    LEFT JOIN `{fq_dataset}.catalogueproduits` c ON c.ean = r.ean
    WHERE c.ean IS NULL
    ORDER BY r.ean
    {lim}
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("run_date", "DATE", run_date),
        ]
    )
    rows = client.query(sql, job_config=job_config).result()
    return [str(r["ean"]) for r in rows]


def run() -> None:
    load_dotenv()
    settings = load_settings()
    execution_date = _execution_date()
    started_at = utcnow_iso()
    metrics: Dict[str, Any] = {}
    quality_gates: List[Dict[str, Any]] = []

    try:
        wait_for_upstream_worker(settings, execution_date, "worker_ingestion")

        if not settings.use_gcp:
            logger.warning("worker_off : GCP désactivé — enrichissement ignoré (mode démo).")
            finished_at = utcnow_iso()
            metrics = {
                "skipped": True,
                "reason": "GCP_PROJECT_ID non défini",
                "ean_attempted": 0,
                "ean_resolved": 0,
                "resolution_rate": 1.0,
            }
            quality_gates = [
                evaluate_min_threshold(
                    "off_ean_resolution_rate",
                    1.0,
                    settings.quality_gate_ean_resolution,
                )
            ]
            payload = build_worker_signal(
                worker_name="worker_off",
                execution_date=execution_date,
                status=STATUS_SUCCESS,
                started_at=started_at,
                finished_at=finished_at,
                metrics=metrics,
                quality_gates=quality_gates,
            )
            _persist_signal(settings, execution_date, payload)
            return

        bq = bigquery.Client(project=settings.project_id)
        fq = f"{settings.project_id}.{settings.bq_dataset}"
        ensure_dataset_and_silver_tables(bq, settings.project_id, settings.bq_dataset)

        eans = _list_eans_to_enrich(bq, fq, execution_date, settings.off_max_products)
        logger.info(f"EAN à enrichir : {len(eans)}")

        import time as time_module

        catalogue_rows: List[Dict[str, Any]] = []
        resolved = 0
        attempted = 0
        for ean in eans:
            attempted += 1
            try:
                payload = fetch_product_json(settings.openfoodfacts_api_base, ean)
                summary = summarize_product(payload)
                if summary["api_status"] == 1:
                    resolved += 1
                catalogue_rows.append(
                    {
                        "ean":         ean,
                        "name":        summary.get("name"),
                        "brand":       summary.get("brand"),
                        "category_l1": summary.get("category_l1"),
                        "category_l2": summary.get("category_l2"),
                        "category_l3": summary.get("category_l3"),
                        "nutriscore":  summary.get("nutriscore"),
                        "nova":        summary.get("nova"),
                        "ecoscore":    summary.get("ecoscore"),
                        "image_url":   summary.get("image_url"),
                        "off_found":   summary.get("off_found", False),
                        "enriched_at": datetime.utcnow().isoformat() + "Z",
                        "source":      "openfoodfacts",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"EAN {ean} : échec API — {exc}")
                catalogue_rows.append(
                    {
                        "ean":         ean,
                        "name":        None,
                        "brand":       None,
                        "category_l1": None,
                        "category_l2": None,
                        "category_l3": None,
                        "nutriscore":  None,
                        "nova":        None,
                        "ecoscore":    None,
                        "image_url":   None,
                        "off_found":   False,
                        "enriched_at": datetime.utcnow().isoformat() + "Z",
                        "source":      "openfoodfacts",
                    }
                )
            time_module.sleep(0.15)

        if catalogue_rows:
            insert_rows_in_batches(bq, f"{fq}.catalogueproduits", catalogue_rows, batch_size=2000)

        resolution_rate = (resolved / attempted) if attempted else 1.0
        metrics = {
            "ean_attempted": attempted,
            "ean_resolved": resolved,
            "resolution_rate": resolution_rate,
        }
        quality_gates = [
            evaluate_min_threshold(
                "off_ean_resolution_rate",
                resolution_rate,
                settings.quality_gate_ean_resolution,
            )
        ]
        raise_if_quality_gates_failed(quality_gates)

        finished_at = utcnow_iso()
        payload = build_worker_signal(
            worker_name="worker_off",
            execution_date=execution_date,
            status=STATUS_SUCCESS,
            started_at=started_at,
            finished_at=finished_at,
            metrics=metrics,
            quality_gates=quality_gates,
        )
        dest = _persist_signal(settings, execution_date, payload)
        logger.success(f"worker_off terminé — signal : {dest}")

    except Exception as exc:  # noqa: BLE001
        logger.exception("worker_off en échec")
        finished_at = utcnow_iso()
        payload = build_worker_signal(
            worker_name="worker_off",
            execution_date=execution_date,
            status=STATUS_FAILED,
            started_at=started_at,
            finished_at=finished_at,
            metrics=metrics,
            quality_gates=quality_gates,
            error_message=str(exc),
        )
        _persist_signal(settings, execution_date, payload)
        if isinstance(exc, QualityGateError):
            raise SystemExit(1) from exc
        raise SystemExit(1) from exc


def main() -> None:
    run()


if __name__ == "__main__":
    main()
