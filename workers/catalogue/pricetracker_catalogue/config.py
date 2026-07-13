
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
        description="GCP project_id. Vide en local → résolu par ADC.",
    )
    #prt_gcp_region: str = Field(default="europe-west1")
    prt_gcp_region: str = Field(default="us-central1")


    prt_bronze_bucket: str = Field(default="price-tracker-prod-01-bronze")
    #prt_catalogue_parquet_blob: str = Field(default="prices.parquet")
    prt_catalogue_parquet_blob: str = Field(
        default="open-prices/dt=2026-06-11/snapshot.parquet"
    )


    prt_off_image_base_url: str = Field(
        default="https://prices.openfoodfacts.org/img/"
    )


    prt_db_instance: str = Field(
        default="price-tracker-prod-01:europe-west1:prt-prod-sql-main"
    )
    prt_db_name: str = Field(default="price_tracker")
    prt_db_user: str = Field(default="pt_app")
    prt_db_password: str = Field(
        default="",
        description="Injecté par Secret Manager en prod, variable locale en dev.",
    )


    prt_filter_country_codes: str = Field(
        default="FR" #,GP,GF,MQ,RE,YT,PM,MF,BL,WF,NC,PF"
    )
    prt_filter_proof_type: str = Field(default="RECEIPT")


    #prt_vertex_model: str = Field(default="gemini-1.5-flash-002")
    prt_vertex_model: str = Field(default="gemini-2.5-flash")
    #prt_llm_max_tokens: int = Field(default=1000)
    prt_llm_max_tokens: int = Field(default=8192)
    prt_llm_temperature: float = Field(default=0.0)
    prt_llm_max_candidats: int = Field(
        default=30,
        description="Nombre max de produits candidats envoyés au LLM par ticket.",
    )


    prt_confidence_threshold: float = Field(
        default=0.7,
        description="Seuil de confiance minimum pour enregistrer un match.",
    )
    prt_image_download_timeout: int = Field(default=10)

    prt_llm_delay_seconds: float = Field(default=0.5)


    prt_oidc_disable: bool = Field(
        default=False,
        description="Bypass OIDC en dev local. JAMAIS true en prod.",
    )


    @property
    def allowed_countries(self) -> frozenset[str]:
        return frozenset(
            s.strip().upper()
            for s in self.prt_filter_country_codes.split(",")
            if s.strip()
        )


def get_settings() -> Settings:
    return Settings()
