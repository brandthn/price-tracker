"""Settings worker alertes — env vars pydantic-settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # GCP -----------------------------------------------------------------
    google_cloud_project: str = Field(default="")
    prt_gcp_region: str = Field(default="europe-west1")

    # BigQuery ------------------------------------------------------------
    prt_bq_dataset_gold: str = Field(default="prt_prod_gold")
    prt_bq_table_rankings: str = Field(default="rankings_produits")
    prt_bq_table_anomalies: str = Field(default="anomalies_detected")
    prt_bq_location: str = Field(default="EU")

    # GCS pour le rapport -------------------------------------------------
    prt_alerts_bucket: str = Field(
        default="",
        description="Bucket GCS où le rapport JSON est écrit. Vide = log-only.",
    )
    prt_alerts_prefix: str = Field(default="alerts")

    # Paramètres métier ---------------------------------------------------
    prt_alertes_top_rankings: int = Field(
        default=50,
        description="Nombre de produits en hausse retenus dans le rapport.",
    )
    prt_alertes_min_pct_change: float = Field(
        default=0.05,
        description="Seuil minimum de variation (5%) pour qu'un ranking soit considéré alertable.",
    )
    prt_alertes_top_anomalies: int = Field(
        default=100,
        description="Nombre d'anomalies retenues dans le rapport.",
    )
    prt_alertes_lookback_weeks: int = Field(
        default=2,
        description="Nombre de semaines à regarder en arrière depuis run_date pour les signaux.",
    )

    # OIDC ----------------------------------------------------------------
    prt_oidc_disable: bool = Field(default=False)
    prt_oidc_required_audience: str = Field(default="")
    prt_oidc_allowed_issuers: str = Field(
        default="https://accounts.google.com,accounts.google.com"
    )
    prt_oidc_allowed_service_accounts: str = Field(default="")

    @property
    def allowed_issuers(self) -> list[str]:
        return [s.strip() for s in self.prt_oidc_allowed_issuers.split(",") if s.strip()]

    @property
    def allowed_service_accounts(self) -> list[str]:
        return [
            s.strip()
            for s in self.prt_oidc_allowed_service_accounts.split(",")
            if s.strip()
        ]


def get_settings() -> Settings:
    return Settings()
