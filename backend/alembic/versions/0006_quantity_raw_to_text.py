"""products.quantity_raw : varchar(100) → text (le texte libre OFF `quantity`
peut être arbitrairement long).

Revision ID: 0006_quantity_raw_to_text
Revises: 0005_products_reco_columns
Create Date: 2026-07-06

⚠️ id volontairement COURT : `alembic_version.version_num` = VARCHAR(32).

`quantity_raw` stocke le texte OFF `quantity` brut (« 500 g ») à des fins
d'affichage/audit — JAMAIS calculé dessus. Mesuré sur le dump OFF (notre
catalogue) : longueur jusqu'à **3530 caractères** (des contributeurs y collent
des descriptions), donc `varchar(100)` déborde (`StringDataRightTruncationError`).
`text` (illimité) est le type correct pour ce champ non structuré. La quantité
exploitable reste dans `quantity_value` (numeric) + `quantity_unit`.

varchar(100) → text est un cast implicite sûr côté Postgres (pas de réécriture
de table, changement de métadonnée). Idempotent via IF EXISTS pour rester aligné
avec le DDL du worker OFF.
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
    # Retour à varchar(100). USING tronque les valeurs plus longues (nécessaire
    # sinon le cast échoue) — perte assumée : quantity_raw est de l'affichage.
    op.execute(
        "ALTER TABLE products ALTER COLUMN quantity_raw TYPE varchar(100) "
        "USING left(quantity_raw, 100)"
    )
