"""Table tickets — metadonnees d'un ticket uploade.

status : pending (signed url generee) -> uploaded (objet GCS, declenche OCR) ->
ocr_processing -> ocr_done (compte, articles dans prix_extraits) / ocr_failed
(pas de retry auto). validated = user a corrige des lignes.
last_feedback = up/down ; ocr_attempts = nb de passes (tier-1=1, down -> tier-2=2) ;
ocr_model = id exact du modele, complete ocr_engine.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base

TICKET_STATUSES = (
    "pending",
    "uploaded",
    "ocr_processing",
    "ocr_done",
    "ocr_failed",
    "validated",
)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    gcs_path: Mapped[str] = mapped_column(
        String(512),
        doc="gs://bucket/tickets/raw/{user_id}/{uuid}.jpg",
    )

    # renseignes par le worker OCR, NULL avant traitement
    enseigne: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_ticket: Mapped[datetime.date | None] = mapped_column(nullable=True)
    total_eur: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(nullable=True)
    ocr_model: Mapped[str | None] = mapped_column(nullable=True)
    ocr_duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    ocr_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Boucle de feedback OCR.
    ocr_attempts: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    last_feedback: Mapped[str | None] = mapped_column(String(8), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
