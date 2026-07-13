"""products: socle reco substituts — quantité normalisée + chemin de catégories OFF.

Revision ID: 0005_products_reco_columns
Revises: 0004_seed_aliases_catalogue
Create Date: 2026-07-06

id court : alembic_version.version_num = VARCHAR(32).

Ajoute a products (partagee avec le worker OFF) les colonnes OFF necessaires a la
reco de substituts :
- quantity_raw   : texte OFF brut ("500 g"), affichage/audit, jamais pour le calcul.
- quantity_value : valeur numerique en unite canonique.
- quantity_unit  : 'kg' | 'L' (g->kg, ml->L).
- categories_tags: chemin OFF complet (general -> specifique) ; le tier categorie se
                   calcule sur la profondeur du prefixe commun, d'ou le chemin entier.

quantity_value/unit NULL = exclu du €/unite (couverture ~86.5%). categories_tags NULL
possible (~92.8%). ADD COLUMN IF NOT EXISTS (products bootstrappee par le worker OFF),
aligne sur workers/off/pricetracker_off/pg.py.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_products_reco_columns"
down_revision: str | Sequence[str] | None = "0004_seed_aliases_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS quantity_raw varchar(100)")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS quantity_value numeric(12, 6)")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS quantity_unit varchar(8)")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS categories_tags text[]")


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS categories_tags")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS quantity_unit")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS quantity_value")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS quantity_raw")
