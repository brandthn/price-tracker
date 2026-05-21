"""Runtime configuration, loaded from env vars (Cloud Run injects them).

Conventions :
- Standards GCP (`GOOGLE_CLOUD_PROJECT`) lus sans préfixe.
- Custom worker → préfixe `PRT_` (sauf `HF_TOKEN` qui suit la convention HF).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    google_cloud_project: str = Field(
        default="",
        description="GCP project_id. Vide en local → résolu par ADC au runtime.",
    )
    prt_gcp_region: str = Field(default="europe-west1")

    prt_bronze_bucket: str = Field(default="price-tracker-prod-01-bronze")
    prt_bq_dataset_silver: str = Field(default="prt_prod_silver")
    prt_bq_table_open_prices: str = Field(default="open_prices_clean")

    prt_hf_dataset: str = Field(default="openfoodfacts/open-prices")
    prt_hf_filename: str = Field(default="prices.parquet")
    prt_hf_revision: str = Field(default="main")
    hf_token: str | None = Field(default=None)

    prt_filter_country_code: str = Field(default="FR")

    # OIDC verification ---------------------------------------------------
    prt_oidc_disable: bool = Field(
        default=False,
        description="Bypass de la vérif OIDC en dev local. JAMAIS true en prod.",
    )
    prt_oidc_required_audience: str = Field(
        default="",
        description="Audience attendue dans le JWT (URL exacte du service Cloud Run).",
    )
    prt_oidc_allowed_issuers: str = Field(
        default="https://accounts.google.com,accounts.google.com",
        description="Issuers OIDC autorisés (CSV).",
    )
    prt_oidc_allowed_service_accounts: str = Field(
        default="",
        description="Emails SA autorisés à invoquer /run (CSV). Vide = tout SA Google passé l'audience.",
    )

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
