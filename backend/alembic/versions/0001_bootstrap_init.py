"""bootstrap: extension pgvector + tables users/tickets/prix_extraits/aliases/products/basket/notif.

Revision ID: 0001_bootstrap_init
Revises:
Create Date: 2026-05-25

CREATE EXTENSION vector demande un superuser : pt_app ne l'a pas, creer
l'extension a la main via la console Cloud SQL si la migration echoue (IF NOT
EXISTS = idempotent). products est cree par le worker OFF au bootstrap, on la
(re)cree ici en IF NOT EXISTS ; DDL a garder aligne avec pg.py.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_bootstrap_init"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # products : partagee avec le worker OFF, IF NOT EXISTS car deja peuplee.
    # DDL a matcher workers/off/pricetracker_off/pg.py
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            ean         varchar(13) PRIMARY KEY,
            name        varchar(500),
            brand       varchar(200),
            category_l1 varchar(200),
            category_l2 varchar(200),
            category_l3 varchar(200),
            nutriscore  varchar(1),
            nova        varchar(1),
            ecoscore    varchar(1),
            image_url   varchar(1024),
            off_found   boolean NOT NULL DEFAULT false,
            embedding   vector(768),
            enriched_at timestamptz DEFAULT now(),
            source      varchar(50) DEFAULT 'openfoodfacts'
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_category_l3 ON products (category_l3)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_off_found ON products (off_found)")
    # ivfflat cosine, lists=100 = compromis qualite/latence pour ~10k-100k rows ;
    # creation potentiellement longue, IF NOT EXISTS
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_products_embedding_cosine
        ON products USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
        """
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("firebase_uid", sa.String(128), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("departement", sa.String(3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_firebase_uid", "users", ["firebase_uid"])

    op.create_table(
        "tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("gcs_path", sa.String(512), nullable=False),
        sa.Column("enseigne", sa.String(100), nullable=True),
        sa.Column("date_ticket", sa.Date(), nullable=True),
        sa.Column("total_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("ocr_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tickets_user_id", "tickets", ["user_id"])
    op.create_index("ix_tickets_status", "tickets", ["status"])

    op.create_table(
        "prix_extraits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_index", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.String(300), nullable=False),
        sa.Column("ean", sa.String(13), nullable=True),
        sa.Column("produit_nom", sa.String(300), nullable=True),
        sa.Column("quantity", sa.Numeric(10, 3), nullable=True),
        sa.Column("price_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column(
            "needs_validation", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "validated_by_user", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_prix_extraits_ticket_id", "prix_extraits", ["ticket_id"])
    op.create_index("ix_prix_extraits_ean", "prix_extraits", ["ean"])
    op.create_index(
        "ix_prix_extraits_validated_by_user",
        "prix_extraits",
        ["validated_by_user"],
    )

    op.create_table(
        "product_aliases",
        sa.Column("raw_text", sa.String(300), nullable=False),
        sa.Column("enseigne", sa.String(100), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("ean", sa.String(13), nullable=True),
        sa.Column("produit_nom", sa.String(300), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "validated_by_user", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("raw_text", "enseigne", "source", name="product_aliases_pk"),
    )
    op.create_index("ix_product_aliases_ean", "product_aliases", ["ean"])
    op.create_index(
        "ix_product_aliases_validated_by_user",
        "product_aliases",
        ["validated_by_user"],
    )

    op.create_table(
        "user_basket_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ean", sa.String(13), nullable=False),
        sa.Column(
            "purchase_count_6m", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("avg_quantity", sa.Float(), nullable=True),
        sa.Column("last_purchased_at", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "ean", name="user_basket_history_user_ean_uq"),
    )
    op.create_index("ix_user_basket_history_user_id", "user_basket_history", ["user_id"])
    op.create_index("ix_user_basket_history_ean", "user_basket_history", ["ean"])

    op.create_table(
        "notification_prefs",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "threshold_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default=sa.text("5.0"),
        ),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="weekly"),
        sa.Column(
            "favorite_enseignes", postgresql.ARRAY(sa.String(100)), nullable=True
        ),
        sa.Column("fcm_token", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("notification_prefs")
    op.drop_index("ix_user_basket_history_ean", table_name="user_basket_history")
    op.drop_index("ix_user_basket_history_user_id", table_name="user_basket_history")
    op.drop_table("user_basket_history")
    op.drop_index("ix_product_aliases_validated_by_user", table_name="product_aliases")
    op.drop_index("ix_product_aliases_ean", table_name="product_aliases")
    op.drop_table("product_aliases")
    op.drop_index("ix_prix_extraits_validated_by_user", table_name="prix_extraits")
    op.drop_index("ix_prix_extraits_ean", table_name="prix_extraits")
    op.drop_index("ix_prix_extraits_ticket_id", table_name="prix_extraits")
    op.drop_table("prix_extraits")
    op.drop_index("ix_tickets_status", table_name="tickets")
    op.drop_index("ix_tickets_user_id", table_name="tickets")
    op.drop_table("tickets")
    op.drop_index("ix_users_firebase_uid", table_name="users")
    op.drop_table("users")
    # products pas droppe : table partagee avec le worker OFF (cycle de vie independant)
