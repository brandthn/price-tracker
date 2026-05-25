"""Settings worker OCR — env vars pydantic-settings."""

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
    prt_bronze_bucket: str = Field(default="")

    # OCR -----------------------------------------------------------------
    prt_ocr_engine: str = Field(default="groq")
    prt_ocr_confidence_threshold: float = Field(default=0.55)

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

    # Future-phase (declared, unused) -------------------------------------
    prt_models_bucket: str | None = None
    prt_ocr_model_uri: str | None = None
    prt_ean_match_cosine_threshold: float = Field(default=0.78)
    prt_ean_match_top_k: int = Field(default=5)
    prt_ean_fuzzy_min_score: int = Field(default=82)
    prt_vertex_model: str = Field(default="text-embedding-004")
    prt_vertex_output_dim: int = Field(default=768)
    prt_vertex_task_type: str = Field(default="RETRIEVAL_QUERY")

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
