"""
Worker ingestion — conforme au guide (§5 worker 1, §6 quality gates).

Étapes :
  1. Téléchargement optionnel du snapshot Hugging Face (Bronze local Parquet).
  2. Copie optionnelle vers GCS (chemin type `open-prices/date=YYYY-MM-DD/snapshot.parquet`).
  3. Lecture du Parquet par lots, mapping HF → cleaner, nettoyage Silver.
  4. Insertion BigQuery (`openpricesclean`, `openpricesrejections`) si `GCP_PROJECT_ID` est défini.
  5. Quality gates (taux d’acceptation, couverture enseigne) — bloquants.
  6. Publication du signal JSON (GCS ou répertoire local `artifacts/`).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pyarrow.parquet as pq
from dotenv import load_dotenv
from loguru import logger

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKER_DIR = Path(__file__).resolve().parent
for _p in (_REPO_ROOT, _WORKER_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from download_open_prices import telecharger_open_prices, bronze_local_parquet_path  # noqa: E402

from google.cloud import bigquery, storage  # noqa: E402

from shared.bq_io import insert_rows_in_batches  # noqa: E402
from shared.bq_setup import ensure_dataset_and_silver_tables  # noqa: E402
from shared.cleaner import clean_price_record  # noqa: E402
from shared.config import load_settings, utc_today_iso  # noqa: E402
from shared.hf_mapping import hf_open_prices_row_to_cleaner_record  # noqa: E402

# Enrichissements Silver — même logique que local_pipeline/silver.py
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_pipeline.silver_enrichments import (  # noqa: E402
    validate_ean,
    normalize_store_brand,
    standardize_city,
)
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


def _execution_date() -> str:
    return os.getenv("EXECUTION_DATE") or utc_today_iso()


def _sanitize_cell(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    if isinstance(value, float) and (value != value):  # NaN
        return None
    return value


def _row_dict_from_pyarrow_batch(batch: Any, row_index: int) -> Dict[str, Any]:
    cols = batch.to_pydict()
    names = list(cols.keys())
    if not names:
        return {}
    return {k: _sanitize_cell(cols[k][row_index]) for k in names}


def _iter_parquet_rows(path: Path, max_rows: Optional[int]) -> Iterator[Dict[str, Any]]:
    pf = pq.ParquetFile(path)
    yielded = 0
    for batch in pf.iter_batches(batch_size=50_000):
        n = batch.num_rows
        for i in range(n):
            if max_rows is not None and yielded >= max_rows:
                return
            yield _row_dict_from_pyarrow_batch(batch, i)
            yielded += 1


def _prepare_clean_bq_row(
    row: Dict[str, Any],
    pipeline_run_date: date,
) -> Dict[str, Any]:
    out = dict(row)
    out["pipeline_run_date"] = pipeline_run_date
    if isinstance(out.get("price_date"), str):
        out["price_date"] = datetime.fromisoformat(out["price_date"]).date()
    if isinstance(out.get("week_start_date"), str):
        out["week_start_date"] = datetime.fromisoformat(out["week_start_date"]).date()
    if "raw_payload" in out and isinstance(out["raw_payload"], dict):
        out["raw_payload"] = json.dumps(out["raw_payload"], ensure_ascii=False)
    return out


def _prepare_rejection_bq_row(
    row: Dict[str, Any],
    pipeline_run_date: date,
) -> Dict[str, Any]:
    out = dict(row)
    out["pipeline_run_date"] = pipeline_run_date
    if out.get("raw_price") is not None and not isinstance(out["raw_price"], str):
        out["raw_price"] = str(out["raw_price"])
    rp = out.get("raw_payload")
    if isinstance(rp, dict):
        out["raw_payload"] = json.dumps(rp, ensure_ascii=False)
    return out


def _upload_bronze_gcs(
    storage_client: storage.Client,
    bucket: str,
    execution_date: str,
    local_path: Path,
) -> str:
    dest = f"open-prices/date={execution_date}/snapshot.parquet"
    blob = storage_client.bucket(bucket).blob(dest)
    blob.upload_from_filename(str(local_path))
    return f"gs://{bucket}/{dest}"


def _wait_upstream_if_needed(settings, execution_date: str) -> None:
    upstream = os.getenv("UPSTREAM_WORKER")
    if not upstream:
        return
    wait_for_upstream_worker(settings, execution_date, upstream)


def _persist_signal(
    settings,
    execution_date: str,
    payload: Dict[str, Any],
) -> str:
    if settings.use_gcp and settings.gcs_signals_bucket:
        client = storage.Client(project=settings.project_id)
        return write_signal_to_bucket(
            storage_client=client,
            bucket_name=settings.gcs_signals_bucket,
            execution_date=execution_date,
            worker_name="worker_ingestion",
            signal_payload=payload,
        )
    path = write_local_signal(Path("./artifacts"), execution_date, "worker_ingestion", payload)
    return str(path)


def run() -> None:
    load_dotenv()
    settings = load_settings()
    execution_date = _execution_date()
    run_date = datetime.strptime(execution_date, "%Y-%m-%d").date()
    started_at = utcnow_iso()
    metrics: Dict[str, Any] = {}
    quality_gates: List[Dict[str, Any]] = []

    try:
        _wait_upstream_if_needed(settings, execution_date)

        if not settings.skip_download:
            telecharger_open_prices(settings.raw_data_path)
        local_parquet = bronze_local_parquet_path(settings.raw_data_path)
        if not local_parquet.is_file():
            raise FileNotFoundError(f"Parquet introuvable : {local_parquet}")

        if settings.use_gcp and settings.gcs_bronze_bucket:
            sc = storage.Client(project=settings.project_id)
            uri = _upload_bronze_gcs(sc, settings.gcs_bronze_bucket, execution_date, local_parquet)
            logger.info(f"Bronze GCS : {uri}")

        cfg = settings.cleaner_config(reference_date=run_date)

        total = accepted = with_brand = 0
        clean_buffer: List[Dict[str, Any]] = []
        reject_buffer: List[Dict[str, Any]] = []

        clean_table = (
            f"{settings.project_id}.{settings.bq_dataset}.openpricesclean"
            if settings.use_gcp
            else None
        )
        reject_table = (
            f"{settings.project_id}.{settings.bq_dataset}.openpricesrejections"
            if settings.use_gcp
            else None
        )

        bq_client: Optional[bigquery.Client] = None
        if settings.use_gcp:
            bq_client = bigquery.Client(project=settings.project_id)
            ensure_dataset_and_silver_tables(
                bq_client,
                settings.project_id,
                settings.bq_dataset,
            )

        for raw in _iter_parquet_rows(local_parquet, settings.ingest_max_rows):
            total += 1
            mapped = hf_open_prices_row_to_cleaner_record(raw)
            clean_row, rejection = clean_price_record(mapped, config=cfg)

            if clean_row is None:
                if rejection and reject_table and bq_client:
                    reject_buffer.append(_prepare_rejection_bq_row(rejection, run_date))
                    if len(reject_buffer) >= 5000:
                        insert_rows_in_batches(bq_client, reject_table, reject_buffer)
                        reject_buffer.clear()
                continue

            # ── Enrichissements Silver ──────────────────────────────────────
            # Validation EAN-13/8 (checksum)
            ean_ok, ean_reason = validate_ean(clean_row.get("product_code"))
            if not ean_ok:
                if reject_table and bq_client:
                    rej = {
                        "id":           clean_row.get("id"),
                        "product_code": clean_row.get("product_code"),
                        "reason":       "INVALID_EAN",
                        "details":      ean_reason,
                        "currency":     clean_row.get("currency"),
                        "raw_price":    str(clean_row.get("price_eur", "")),
                        "price_date":   clean_row.get("price_date"),
                        "country_code": clean_row.get("country_code"),
                        "proof_type":   clean_row.get("proof_type"),
                        "rejected_at":  datetime.utcnow().isoformat() + "Z",
                    }
                    reject_buffer.append(_prepare_rejection_bq_row(rej, run_date))
                    if len(reject_buffer) >= 5000:
                        insert_rows_in_batches(bq_client, reject_table, reject_buffer)
                        reject_buffer.clear()
                continue

            # Normalisation enseigne : adresse OSM → "E.Leclerc", "Carrefour"...
            raw_brand = clean_row.get("store_brand")
            clean_row = dict(clean_row)
            clean_row["store_brand_normalized"] = normalize_store_brand(raw_brand)

            # Standardisation ville : "PARIS 17e Arrondissement" → "Paris"
            clean_row["city"] = standardize_city(clean_row.get("city"))

            accepted += 1
            if clean_row.get("store_brand_normalized"):
                with_brand += 1

            if clean_table and bq_client:
                clean_buffer.append(_prepare_clean_bq_row(clean_row, run_date))
                if len(clean_buffer) >= 5000:
                    insert_rows_in_batches(bq_client, clean_table, clean_buffer)
                    clean_buffer.clear()

        if clean_buffer and bq_client and clean_table:
            insert_rows_in_batches(bq_client, clean_table, clean_buffer)
        if reject_buffer and bq_client and reject_table:
            insert_rows_in_batches(bq_client, reject_table, reject_buffer)

        acceptance_rate = accepted / total if total else 0.0
        store_coverage = with_brand / accepted if accepted else 0.0

        metrics = {
            "total_records": total,
            "accepted_records": accepted,
            "rejected_records": total - accepted,
            "acceptance_rate": acceptance_rate,
            "store_brand_coverage_rate": store_coverage,
            "bronze_local_path": str(local_parquet),
            "ingest_max_rows": settings.ingest_max_rows,
        }

        quality_gates = [
            evaluate_min_threshold(
                "ingestion_acceptance_rate",
                acceptance_rate,
                settings.quality_gate_acceptance_rate,
            ),
            evaluate_min_threshold(
                "ingestion_store_brand_coverage",
                store_coverage,
                settings.quality_gate_store_coverage,
            ),
        ]
        raise_if_quality_gates_failed(quality_gates)

        finished_at = utcnow_iso()
        payload = build_worker_signal(
            worker_name="worker_ingestion",
            execution_date=execution_date,
            status=STATUS_SUCCESS,
            started_at=started_at,
            finished_at=finished_at,
            metrics=metrics,
            quality_gates=quality_gates,
        )
        dest = _persist_signal(settings, execution_date, payload)
        logger.success(f"Ingestion terminée — signal : {dest}")

    except Exception as exc:  # noqa: BLE001 — journaliser puis signal FAILED
        logger.exception("Ingestion en échec")
        finished_at = utcnow_iso()
        payload = build_worker_signal(
            worker_name="worker_ingestion",
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
