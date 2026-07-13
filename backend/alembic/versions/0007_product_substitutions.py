"""product_substitutions : paires substitut→produit précalculées (reco Étape 2).

Revision ID: 0007_product_substitutions
Revises: 0006_quantity_raw_to_text
Create Date: 2026-07-06

id court : alembic_version.version_num = VARCHAR(32).

Cache precalcule par le worker off : par produit source, ses substituts moins chers
au €/unite et comparables (kNN pgvector + accord categoriel), score + tier. Recompute
= TRUNCATE + INSERT. DROP + recreate : cache derive sans consommateur live (l'endpoint
/products/{ean}/substitutes lit pgvector directement), regenere par le worker.
tier 1 sur / 2 probable / 3 elargi (categorie) ; score = confiance [0,1], cosine +
cat_agreement = ses composantes ; prix au €/unite, jamais au prix paquet.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_product_substitutions"
down_revision: str | Sequence[str] | None = "0006_quantity_raw_to_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # remplace l'ancien schema sans tier ; cache derive regenere par le worker, fresh DB = no-op
    op.execute("DROP TABLE IF EXISTS product_substitutions")
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
