"""ocr_feedback_loop: table ocr_feedback + colonnes feedback/retry sur tickets.

Revision ID: 0003_ocr_feedback_loop
Revises: 0002_ocr_schema_additions
Create Date: 2026-06-19

Boucle de feedback OCR. Le ticket est compte des l'OCR ; un avis down relance un
re-OCR tier-2. Feedbacks historises pour analyse. Additif uniquement.

tickets :
  + ocr_attempts integer NOT NULL DEFAULT 1  — nb de passes OCR (tier-1 = 1)
  + last_feedback text                       — dernier up/down
  + ocr_model text                           — id exact du modele
ocr_feedback : historique (une ligne par avis, pas d'upsert).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_ocr_feedback_loop"
down_revision: str | Sequence[str] | None = "0002_ocr_schema_additions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("ocr_attempts", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("tickets", sa.Column("last_feedback", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("ocr_model", sa.Text(), nullable=True))

    op.create_table(
        "ocr_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Text(), nullable=False),
        sa.Column(
            "ocr_attempt",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            doc="N° de la passe OCR notee.",
        ),
        sa.Column("ocr_engine", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("rating IN ('up', 'down')", name="ck_ocr_feedback_rating"),
    )
    op.create_index("ix_ocr_feedback_ticket_id", "ocr_feedback", ["ticket_id"])
    op.create_index("ix_ocr_feedback_user_id", "ocr_feedback", ["user_id"])
    op.create_index("ix_ocr_feedback_rating", "ocr_feedback", ["rating"])


def downgrade() -> None:
    op.drop_index("ix_ocr_feedback_rating", table_name="ocr_feedback")
    op.drop_index("ix_ocr_feedback_user_id", table_name="ocr_feedback")
    op.drop_index("ix_ocr_feedback_ticket_id", table_name="ocr_feedback")
    op.drop_table("ocr_feedback")
    op.drop_column("tickets", "ocr_model")
    op.drop_column("tickets", "last_feedback")
    op.drop_column("tickets", "ocr_attempts")
