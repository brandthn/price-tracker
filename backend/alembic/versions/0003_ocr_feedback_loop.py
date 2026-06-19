"""ocr_feedback_loop: table ocr_feedback + colonnes feedback/retry sur tickets.

Revision ID: 0003_ocr_feedback_loop
Revises: 0002_ocr_schema_additions
Create Date: 2026-06-19

Boucle de feedback OCR (👍/👎). L'utilisateur ne valide plus chaque ligne :
le ticket est pris en compte dès l'OCR. Un 👎 relance un re-OCR par un second
LLM (tier-2). Tous les feedbacks sont historisés pour analyser a posteriori
où le système s'est trompé.

Changements (additifs uniquement — aucun rename, aucune suppression) :

tickets :
  + ocr_attempts integer NOT NULL DEFAULT 1  — nombre de passes OCR (tier-1 = 1)
  + last_feedback text                       — dernier 'up'/'down' (accès rapide UI)
  + ocr_model text                           — id exact du modèle (complète ocr_engine)

nouvelle table ocr_feedback :
  historique complet (une ligne par avis, pas d'upsert) pour analyse.
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
    # 1) tickets — colonnes feedback / retry
    op.add_column(
        "tickets",
        sa.Column("ocr_attempts", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("tickets", sa.Column("last_feedback", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("ocr_model", sa.Text(), nullable=True))

    # 2) ocr_feedback — historique des avis 👍/👎
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
            doc="N° de la passe OCR notée (pour savoir quel modèle s'est trompé).",
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
