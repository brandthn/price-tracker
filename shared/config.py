"""Chargement centralisé des paramètres d’environnement (aligné sur `.env.example`)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import FrozenSet, Optional

from shared.cleaner import (
    DEFAULT_ALLOWED_COUNTRIES,
    DEFAULT_ALLOWED_CURRENCIES,
    DEFAULT_ALLOWED_PROOF_TYPES,
    CleanerConfig,
)


def _split_csv(name: str, default: str) -> FrozenSet[str]:
    raw = os.getenv(name, default)
    return frozenset(part.strip().upper() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class PipelineSettings:
    project_id: Optional[str]
    region: str
    bq_dataset: str
    gcs_bronze_bucket: Optional[str]
    gcs_signals_bucket: Optional[str]
    gcs_artifacts_bucket: Optional[str]
    openfoodfacts_api_base: str
    hf_dataset: str
    hf_view: str
    raw_data_path: str
    skip_download: bool
    ingest_max_rows: Optional[int]
    off_max_products: Optional[int]
    signal_max_wait_seconds: int
    signal_poll_interval_seconds: int
    min_observations_for_index: int
    quality_gate_acceptance_rate: float
    quality_gate_store_coverage: float
    quality_gate_ean_resolution: float
    log_level: str
    environment: str

    @property
    def use_gcp(self) -> bool:
        return bool(self.project_id)

    def cleaner_config(self, reference_date: Optional[date] = None) -> CleanerConfig:
        return CleanerConfig(
            allowed_countries=set(
                _split_csv("ALLOWED_COUNTRIES", ",".join(sorted(DEFAULT_ALLOWED_COUNTRIES)))
            ),
            allowed_currencies=set(
                _split_csv("ALLOWED_CURRENCIES", ",".join(sorted(DEFAULT_ALLOWED_CURRENCIES)))
            ),
            allowed_proof_types=set(
                _split_csv("ALLOWED_PROOF_TYPES", ",".join(sorted(DEFAULT_ALLOWED_PROOF_TYPES)))
            ),
            min_price_eur=Decimal(os.getenv("MIN_PRICE_EUR", "0.01")),
            max_price_eur=Decimal(os.getenv("MAX_PRICE_EUR", "500.00")),
            reference_date=reference_date or date.today(),
        )


def utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load_settings() -> PipelineSettings:
    return PipelineSettings(
        project_id=os.getenv("GCP_PROJECT_ID") or None,
        region=os.getenv("GCP_REGION", "europe-west9"),
        bq_dataset=os.getenv("BQ_DATASET", "open_prices_dw"),
        gcs_bronze_bucket=os.getenv("GCS_BRONZE_BUCKET") or None,
        gcs_signals_bucket=os.getenv("GCS_SIGNALS_BUCKET") or None,
        gcs_artifacts_bucket=os.getenv("GCS_ARTIFACTS_BUCKET") or None,
        openfoodfacts_api_base=os.getenv(
            "OPENFOODFACTS_API_BASE",
            "https://world.openfoodfacts.org/api/v2/product",
        ).rstrip("/"),
        hf_dataset=os.getenv("HF_DATASET", "openfoodfacts/open-prices"),
        hf_view=os.getenv("HF_VIEW", "prices"),
        raw_data_path=os.getenv("RAW_DATA_PATH", "./raw"),
        skip_download=os.getenv("SKIP_DOWNLOAD", "false").lower() in {"1", "true", "yes"},
        ingest_max_rows=int(os.getenv("INGEST_MAX_ROWS")) if os.getenv("INGEST_MAX_ROWS") else None,
        off_max_products=int(os.getenv("OFF_MAX_PRODUCTS")) if os.getenv("OFF_MAX_PRODUCTS") else None,
        signal_max_wait_seconds=int(os.getenv("SIGNAL_MAX_WAIT_SECONDS", "600")),
        signal_poll_interval_seconds=int(os.getenv("SIGNAL_POLL_INTERVAL_SECONDS", "15")),
        min_observations_for_index=int(os.getenv("MIN_OBSERVATIONS_FOR_INDEX", "3")),
        quality_gate_acceptance_rate=float(os.getenv("QUALITY_GATE_ACCEPTANCE_RATE", "0.60")),
        quality_gate_store_coverage=float(os.getenv("QUALITY_GATE_STORE_COVERAGE", "0.70")),
        quality_gate_ean_resolution=float(os.getenv("QUALITY_GATE_EAN_RESOLUTION", "0.80")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        environment=os.getenv("ENVIRONMENT", "dev"),
    )
