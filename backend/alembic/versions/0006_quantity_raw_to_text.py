"""products.quantity_raw : varchar(100) → text (le texte libre OFF `quantity`
peut être arbitrairement long).

Revision ID: 0006_quantity_raw_to_text
Revises: 0005_products_reco_columns
Create Date: 2026-07-06

id court : alembic_version.version_num = VARCHAR(32).

quantity_raw = texte OFF brut, affichage/audit. Mesure sur le dump : jusqu'a 3530
caracteres -> varchar(100) deborde (StringDataRightTruncationError), text est le bon
type. La quantite exploitable reste dans quantity_value/quantity_unit.
varchar(100) -> text : cast sur cote Postgres, pas de reecriture de table.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_quantity_raw_to_text"
down_revision: str | Sequence[str] | None = "0005_products_reco_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ALTER COLUMN quantity_raw TYPE text")


def downgrade() -> None:
    # retour varchar(100), USING tronque les valeurs longues (sinon le cast echoue)
    op.execute(
        "ALTER TABLE products ALTER COLUMN quantity_raw TYPE varchar(100) "
        "USING left(quantity_raw, 100)"
    )
