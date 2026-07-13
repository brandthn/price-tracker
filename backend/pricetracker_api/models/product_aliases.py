"""Table product_aliases — mapping (libelle brut, enseigne) -> EAN canonique.

Sources : worker OCR (matching pgvector/Levenshtein, validated_by_user=False),
feedback user (PATCH /tickets/{id}/items met true), seed Maty
(source='colleague-matching'). PK composite (raw_text, enseigne, source) : une
meme paire peut venir de plusieurs sources, agregation au lookup.
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, DateTime, PrimaryKeyConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ProductAlias(Base):
    __tablename__ = "product_aliases"

    raw_text: Mapped[str] = mapped_column(String(300))
    enseigne: Mapped[str] = mapped_column(
        String(100),
        doc="Enseigne canonique (Leclerc, Lidl, Carrefour…). Une chaîne vide si inconnue.",
    )
    source: Mapped[str] = mapped_column(
        String(50),
        doc="ocr | user-validation | colleague-matching | manual",
    )

    ean: Mapped[str | None] = mapped_column(String(13), nullable=True, index=True)
    produit_nom: Mapped[str | None] = mapped_column(String(300), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    validated_by_user: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    matched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        PrimaryKeyConstraint("raw_text", "enseigne", "source", name="product_aliases_pk"),
    )
