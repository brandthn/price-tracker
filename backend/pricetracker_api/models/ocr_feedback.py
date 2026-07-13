"""Table ocr_feedback — historique des avis up/down sur l'output OCR.

Une ligne par avis (pas d'upsert) : un re-OCR tier-2 cree une nouvelle ligne avec
ocr_attempt incremente. Sert a analyser quelle passe a produit un resultat errone.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base

FEEDBACK_RATINGS = ("up", "down")


class OcrFeedback(Base):
    __tablename__ = "ocr_feedback"
    __table_args__ = (
        CheckConstraint("rating IN ('up', 'down')", name="ck_ocr_feedback_rating"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    rating: Mapped[str] = mapped_column(Text, index=True, doc="'up' | 'down'")
    ocr_attempt: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", doc="N° de la passe OCR notée."
    )
    ocr_engine: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
