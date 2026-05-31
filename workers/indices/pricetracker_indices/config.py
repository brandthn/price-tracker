"""Settings worker indices — env vars pydantic-settings."""

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
    prt_bq_dataset_silver: str = Field(default="prt_prod_silver")
    prt_bq_dataset_gold: str = Field(default="prt_prod_gold")
    prt_bq_table_open_prices: str = Field(default="open_prices_clean")
    prt_bq_table_aggregats: str = Field(default="aggregats_enseignes")
    prt_bq_table_indices: str = Field(default="indices_inflation")
    prt_bq_table_rankings: str = Field(default="rankings_produits")
    prt_bq_table_anomalies: str = Field(default="anomalies_detected")
    prt_bq_location: str = Field(default="EU")

    # Paramètres métier ---------------------------------------------------
    prt_indices_min_observations: int = Field(
        default=3,
        description="Nombre minimum de relevés pour qu'un agrégat soit publié (statistiquement significatif).",
    )
    prt_indices_window_weeks_aggregats: int = Field(
        default=12,
        description="Fenêtre glissante pour aggregats_enseignes + indices_inflation.",
    )
    prt_indices_window_weeks_rankings: int = Field(
        default=8,
        description="Fenêtre glissante pour rankings_produits + anomalies_detected.",
    )
    prt_indices_z_threshold: float = Field(
        default=3.0,
        description="Seuil |z-score| au-dessus duquel une ligne devient une anomalie.",
    )
    prt_indices_top_n_rankings: int = Field(
        default=500,
        description="Nombre de hausses retenues dans rankings_produits.",
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
