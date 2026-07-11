"""Settings backend FastAPI — env vars pydantic-settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Labels moteur écrits par les workers dans `tickets.ocr_engine` (= la var
# PRT_OCR_ENGINE_LABEL côté Cloud Run). Servent à router l'escalade sur 👎 :
# scratch → moondream → ocr-llm (gemini = terminal).
OCR_ENGINE_SCRATCH = "ocr-vlm-scratch"
OCR_ENGINE_MOONDREAM = "moondream-0.5b"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # --- GCP --------------------------------------------------------------
    google_cloud_project: str = Field(default="")
    prt_gcp_region: str = Field(default="europe-west1")

    # --- App --------------------------------------------------------------
    prt_env: str = Field(default="dev", description="dev | prod")
    prt_log_level: str = Field(default="INFO")
    prt_openapi_enabled: bool = Field(
        default=True,
        description="Si False, /docs et /openapi.json sont désactivés.",
    )
    prt_cors_origins: str = Field(
        default="*",
        description="CSV des origines CORS autorisées. '*' désactive allow_credentials.",
    )

    # --- BigQuery ---------------------------------------------------------
    prt_bq_dataset_silver: str = Field(default="prt_prod_silver")
    prt_bq_dataset_gold: str = Field(default="prt_prod_gold")
    prt_bq_table_catalogue: str = Field(default="catalogue_produits")
    prt_bq_location: str = Field(default="EU")

    # --- GCS Signed URLs --------------------------------------------------
    prt_gcs_bucket_bronze: str = Field(default="")
    prt_signed_url_ttl_min: int = Field(default=15)

    # --- Cloud SQL --------------------------------------------------------
    prt_pg_host: str = Field(default="127.0.0.1")
    prt_pg_port: int = Field(default=5432)
    prt_pg_db: str = Field(default="price_tracker")
    prt_pg_user: str = Field(default="pt_app")
    prt_pg_password: str = Field(default="")
    prt_pg_pool_size: int = Field(default=4)

    # --- Auth -------------------------------------------------------------
    prt_auth_disable: bool = Field(
        default=False,
        description="DEV ONLY : bypass Firebase Auth, retourne un user fake.",
    )

    # --- Feedback loop / escalade re-OCR ---------------------------------
    # Escalade sur 👎 : tier-1 scratch → tier-2 moondream → tier-3 ocr-llm.
    # Le tier-1 est dispatché par la notification GCS (topic `ticket-uploaded`),
    # pas par le backend ; le backend ne pilote que l'escalade.
    prt_ocr_moondream_topic: str = Field(
        default="ocr-vlm-moondream",
        description="Topic Pub/Sub du backend OCR tier-2 (moondream).",
    )
    prt_ocr_retry_topic: str = Field(
        default="ocr-retry",
        description="Topic Pub/Sub du re-OCR tier-3 (ocr-llm / gemini).",
    )
    prt_max_ocr_attempts: int = Field(
        default=5,
        description="Plafond anti-boucle (nb de passes OCR). L'escalade réelle est "
        "bornée par la ladder par engine (2 escalades max) ; ceci n'est qu'un garde-fou.",
    )

    def _topic_path(self, topic: str) -> str:
        """`projects/<proj>/topics/<topic>` attendu par PublisherClient.

        Accepte un nom court (préfixé avec le projet) ou un chemin déjà complet.
        """
        if topic.startswith("projects/"):
            return topic
        return f"projects/{self.google_cloud_project}/topics/{topic}"

    @property
    def ocr_retry_topic_path(self) -> str:
        return self._topic_path(self.prt_ocr_retry_topic)

    @property
    def ocr_escalation_by_engine(self) -> dict[str, str]:
        """`ocr_engine` du dernier OCR → chemin du topic du tier suivant.

        Un engine absent (ex. `gemini`, ou un ticket traité par un worker hors
        pipeline) est terminal : plus d'escalade possible.
        """
        return {
            OCR_ENGINE_SCRATCH: self._topic_path(self.prt_ocr_moondream_topic),
            OCR_ENGINE_MOONDREAM: self.ocr_retry_topic_path,
        }

    @property
    def cors_origins_list(self) -> list[str]:
        raw = [s.strip() for s in self.prt_cors_origins.split(",") if s.strip()]
        return raw or ["*"]

    @property
    def database_url(self) -> str:
        # SQLAlchemy 2.x async + asyncpg.
        return (
            f"postgresql+asyncpg://{self.prt_pg_user}:{self.prt_pg_password}"
            f"@{self.prt_pg_host}:{self.prt_pg_port}/{self.prt_pg_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Tests : réinitialise le cache après monkeypatch des env vars."""
    get_settings.cache_clear()
