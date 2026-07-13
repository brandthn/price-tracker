"""Table products — DDL aligne sur le worker OFF.

Source de verite : workers/off/pricetracker_off/pg.py (DDL embarque). OFF ecrit
en INSERT ON CONFLICT (ean) DO UPDATE ; colonnes NULL si off_found=False.
Toute modif de DDL a repercuter sur pg.py + migration Alembic.
embedding en vector(768) pgvector : pas de binding SQLAlchemy, similarite via
raw SQL (ORDER BY embedding <=> $1::vector).
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class Product(Base):
    __tablename__ = "products"

    ean: Mapped[str] = mapped_column(String(13), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l3: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    nutriscore: Mapped[str | None] = mapped_column(String(1), nullable=True)
    nova: Mapped[str | None] = mapped_column(String(1), nullable=True)
    ecoscore: Mapped[str | None] = mapped_column(String(1), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    off_found: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # embedding non mappe cote ORM (voir 0001_init.py pour vector(768))
    enriched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )
    source: Mapped[str | None] = mapped_column(String(50), nullable=True, default="openfoodfacts")
