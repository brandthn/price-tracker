"""product_substitutions : paires substitut→produit précalculées (reco Étape 2).

Revision ID: 0007_product_substitutions
Revises: 0006_quantity_raw_to_text
Create Date: 2026-07-06

⚠️ id volontairement COURT : `alembic_version.version_num` = VARCHAR(32).

Cache précalculé par le worker `off` (Cloud Run Job, étape séparée de la boucle
d'enrichissement) : pour chaque produit source, ses substituts **moins chers au
€/unité** et **comparables** (kNN pgvector + accord catégoriel), avec un score de
confiance et un tier. Recompute = TRUNCATE + INSERT (comme les tables Gold).

Score (philosophie) : catégorie = signal haute confiance, embedding = filet borné.
- `tier` 1 « sûr » / 2 « probable » / 3 « élargi » (piloté par la catégorie) ;
- `score` = confiance ∈ [0,1] ; `cosine`, `cat_agreement` = ses composantes ;
- prix comparés au **€/unité** (`*_price_per_unit`, `saving_*`) — jamais au prix paquet.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_product_substitutions"
down_revision: str | Sequence[str] | None = "0006_quantity_raw_to_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS product_substitutions (
            source_ean            varchar(13)  NOT NULL,
            target_ean            varchar(13)  NOT NULL,
            tier                  smallint     NOT NULL,
            score                 numeric(6, 4)  NOT NULL,
            cosine                numeric(6, 4)  NOT NULL,
            cat_agreement         numeric(6, 4)  NOT NULL,
            quantity_unit         varchar(8)   NOT NULL,
            source_price_per_unit numeric(12, 4) NOT NULL,
            target_price_per_unit numeric(12, 4) NOT NULL,
            saving_per_unit       numeric(12, 4) NOT NULL,
            saving_pct            numeric(6, 4)  NOT NULL,
            source_price_obs      integer      NOT NULL,
            target_price_obs      integer      NOT NULL,
            computed_at           timestamptz  NOT NULL DEFAULT now(),
            PRIMARY KEY (source_ean, target_ean)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_substitutions_source "
        "ON product_substitutions (source_ean)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_substitutions_tier "
        "ON product_substitutions (tier)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_substitutions")
