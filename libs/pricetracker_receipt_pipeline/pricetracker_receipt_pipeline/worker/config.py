"""Settings de base des workers OCR par backend — env vars pydantic-settings.

Chaque worker hérite de :class:`BaseWorkerSettings` et fixe son
``prt_ocr_engine_label`` par défaut, puis expose SON ``get_settings()``
``@lru_cache`` (le cache reste local au worker pour les tests).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseWorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # GCP -----------------------------------------------------------------
    google_cloud_project: str = Field(default="")
    prt_gcp_region: str = Field(default="europe-west1")

    # OCR -----------------------------------------------------------------
    # Label moteur écrit dans tickets.ocr_engine / ocr_model. Chaque worker
    # le fixe par défaut (paddleocr, moondream-0.5b, groq-llama4-scout, ...).
    prt_ocr_engine_label: str = Field(default="")
    prt_ocr_max_image_mb: int = Field(default=10)

    # Poids modèle (backends à poids locaux : moondream, receipt-vlm, scratch).
    # URI gs:// complète de l'objet ; vide = pas de bootstrap au démarrage.
    prt_model_gcs_uri: str = Field(default="")
    # Second fichier optionnel (ocr-vlm-scratch : tokenizer.json).
    prt_tokenizer_gcs_uri: str = Field(default="")
    prt_model_local_dir: str = Field(default="/tmp/models")

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
