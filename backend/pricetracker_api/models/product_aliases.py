"""Table `product_aliases` — mapping (libellé brut, enseigne) → EAN canonique.

Alimentée par plusieurs sources :
- Worker OCR (Phase 8) : candidats issus du matching pgvector/Levenshtein,
  `validated_by_user=False` jusqu'à la confirmation utilisateur.
- Feedback utilisateur : `PATCH /tickets/{id}/items` met `validated_by_user=True`.
- Seed Maty : script one-shot `scripts/seed_aliases_and_catalogue.py` qui
  ingère un JSONL de mappings (raw_text, enseigne) → ean, marqués
  `source='colleague-matching'`.

PK composite (raw_text, enseigne, source) pour qu'une même paire puisse
exister depuis plusieurs sources (l'agrégation se fait au lookup).
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
