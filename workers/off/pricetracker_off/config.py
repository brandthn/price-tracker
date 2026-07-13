#Settings worker OFF

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # GCP
    google_cloud_project: str = Field(default="")
    prt_gcp_region: str = Field(default="europe-west1")

    # BigQuery
    prt_bq_dataset_silver: str = Field(default="prt_prod_silver")
    prt_bq_table_open_prices: str = Field(default="open_prices_clean")
    prt_bq_table_catalogue: str = Field(default="catalogue_produits")

    # Open Food Facts 
    prt_off_base_url: str = Field(default="https://world.openfoodfacts.org")
    prt_off_user_agent: str = Field(
        default="pricetracker-prt-prod/0.1 (+https://github.com/PriceTracker/contact)",
        description="UA conforme aux conditions d'usage OFF (identification du caller).",
    )
    prt_off_rate_rpm: int = Field(
        default=15,
        description="Politique officielle OFF : 15 req/min/IP sur GET /product.",
    )
    prt_off_max_eans_per_run: int = Field(
        default=2000,
        description="Cap dur (validation utilisateur). Le timeout Cloud Run bornera en pratique à ~800 EAN/run.",
    )
    prt_off_run_timeout_s: int = Field(
        default=3500,
        description="Arrêt élégant avant le timeout Cloud Run gen2 (3600s).",
    )
    prt_off_http_timeout_s: float = Field(default=20.0)
    prt_off_max_retries: int = Field(default=4)

    # Vertex AI 
    prt_vertex_model: str = Field(default="text-embedding-004")
    prt_vertex_batch: int = Field(default=250, description="Max instances par appel Vertex.")
    prt_vertex_task_type: str = Field(
        default="SEMANTIC_SIMILARITY",
        description=(
            "Similarité produit↔produit (reco de substituts) : les deux côtés du "
            "cosinus sont des documents produit. Tout l'espace pgvector doit "
            "partager ce task_type — un même texte donne un vecteur DIFFÉRENT "
            "selon le task_type. ⚠️ La var Terraform PRT_VERTEX_TASK_TYPE du "
            "worker déployé doit être alignée sur cette valeur (apply humain)."
        ),
    )
    prt_vertex_output_dim: int = Field(default=768)

    prt_reco_price_window_weeks: int = Field(default=52)
    prt_reco_price_min_obs: int = Field(default=1)
    prt_reco_knn_k: int = Field(
        default=40, description="Voisins kNN sur-fetchés par source (on filtre ensuite prix + moins cher)."
    )
    prt_reco_top_n: int = Field(default=8, description="Substituts retenus par source.")
    prt_reco_max_per_brand: int = Field(
        default=2, description="Plafond de substituts d'une même marque (diversité)."
    )
    # Score : catégorie dominante, embedding borné
    prt_reco_w_cat: float = Field(default=0.75)
    prt_reco_w_emb: float = Field(default=0.50)
    prt_reco_cos_floor: float = Field(default=0.35)
    prt_reco_cos_ref: float = Field(default=0.75)
    prt_reco_tier1_cat: float = Field(default=0.80)
    prt_reco_tier2_cat: float = Field(default=0.30)

    # Cloud SQL
    prt_pg_host: str = Field(default="")
    prt_pg_port: int = Field(default=5432)
    prt_pg_db: str = Field(default="price_tracker")
    prt_pg_user: str = Field(default="pt_app")
    prt_pg_password: str = Field(default="")
    prt_pg_pool_size: int = Field(default=4)

    # OIDC 
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
