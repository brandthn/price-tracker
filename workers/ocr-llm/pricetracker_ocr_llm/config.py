"""Settings worker OCR tier-2 (LLM Groq) — env vars pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

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

    # OCR LLM -------------------------------------------------------------
    # Modèle Groq vision utilisé pour la seconde passe. Défaut = même modèle que
    # le tier-1 (fiabilité) ; pointer vers un modèle plus performant ensuite.
    prt_ocr_model: str = Field(default="meta-llama/llama-4-scout-17b-16e-instruct")
    prt_ocr_engine_label: str = Field(default="groq")
    prt_ocr_max_image_mb: int = Field(default=10)

    # Cloud SQL -----------------------------------------------------------
    prt_pg_host: str = Field(default="")
    prt_pg_port: int = Field(default=5432)
    prt_pg_db: str = Field(default="price_tracker")
    prt_pg_user: str = Field(default="pt_app")
    prt_pg_password: str = Field(default="")
    prt_pg_pool_size: int = Field(default=4)

    # OIDC ----------------------------------------------------------------
    prt_oidc_disable: bool = Field(default=False)
    prt_oidc_required_audience: str = Field(default="")
    prt_oidc_allowed_issuers: str = Field(
        default="https://accounts.google.com,accounts.google.com"
    )
    prt_oidc_allowed_service_accounts: str = Field(default="")

    # Logging -------------------------------------------------------------
    prt_log_level: str = Field(default="INFO")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
