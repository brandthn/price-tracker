"""ocr_schema_additions: colonnes OCR manquantes + contraintes idempotence.

Revision ID: 0002_ocr_schema_additions
Revises: 0001_bootstrap_init
Create Date: 2026-05-25

Changements (additifs uniquement — aucun rename, aucune suppression) :

tickets :
  + ocr_engine text            — moteur utilisé ("groq", "paddleocr", ...)
  + ocr_duration_ms integer    — durée OCR en millisecondes

prix_extraits :
  + DEFAULT gen_random_uuid()  — permet INSERT sans fournir id (worker OCR)
  + UNIQUE(ticket_id, line_index) — contrainte d'idempotence Pub/Sub replay
  + unit_price numeric(10,2)   — prix unitaire lu sur le ticket
  + line_total numeric(10,2)   — total de la ligne (quantity * unit_price)
  + match_method text          — méthode de matching EAN ("vector"|"fuzzy"|"none")
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ocr_schema_additions"
down_revision: str | Sequence[str] | None = "0001_bootstrap_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) tickets — nouvelles colonnes OCR
    op.add_column("tickets", sa.Column("ocr_engine", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("ocr_duration_ms", sa.Integer(), nullable=True))

    # 2) prix_extraits — DEFAULT sur id pour que le worker insère sans fournir l'UUID
    op.execute(
        "ALTER TABLE prix_extraits ALTER COLUMN id SET DEFAULT gen_random_uuid()"
    )

    # 3) prix_extraits — contrainte UNIQUE pour ON CONFLICT (ticket_id, line_index)
    op.create_unique_constraint(
        "uq_prix_extraits_ticket_line",
        "prix_extraits",
        ["ticket_id", "line_index"],
    )

    # 4) prix_extraits — colonnes OCR worker
    op.add_column("prix_extraits", sa.Column("unit_price", sa.Numeric(10, 2), nullable=True))
    op.add_column("prix_extraits", sa.Column("line_total", sa.Numeric(10, 2), nullable=True))
    op.add_column(
        "prix_extraits",
        sa.Column("match_method", sa.Text(), nullable=True, server_default="none"),
    )


def downgrade() -> None:
    op.drop_column("prix_extraits", "match_method")
    op.drop_column("prix_extraits", "line_total")
    op.drop_column("prix_extraits", "unit_price")
    op.drop_constraint("uq_prix_extraits_ticket_line", "prix_extraits", type_="unique")
    op.execute(
        "ALTER TABLE prix_extraits ALTER COLUMN id DROP DEFAULT"
    )
    op.drop_column("tickets", "ocr_duration_ms")
    op.drop_column("tickets", "ocr_engine")
