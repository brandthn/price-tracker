"""Table `prix_extraits` — lignes articles extraites d'un ticket par l'OCR.

Une ligne par article du ticket. `ean` peut être NULL si l'OCR n'a pas
trouvé de match (utilisateur doit valider). `validated_by_user` passe à
true quand l'utilisateur a confirmé/corrigé.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class PrixExtrait(Base):
    __tablename__ = "prix_extraits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        index=True,
    )
    line_index: Mapped[int] = mapped_column(doc="Position de la ligne dans le ticket (0-based).")

    raw_text: Mapped[str] = mapped_column(String(300), doc="Libellé brut OCR.")
    ean: Mapped[str | None] = mapped_column(
        String(13), nullable=True, index=True, doc="EAN canonique (NULL si non résolu)."
    )
    produit_nom: Mapped[str | None] = mapped_column(String(300), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    price_eur: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    line_total: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    match_method: Mapped[str | None] = mapped_column(nullable=True)

    ocr_confidence: Mapped[float | None] = mapped_column(nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(
        nullable=True, doc="Score similarité EAN (pgvector / fuzzy)."
    )
    needs_validation: Mapped[bool] = mapped_column(Boolean, default=True)
    validated_by_user: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
