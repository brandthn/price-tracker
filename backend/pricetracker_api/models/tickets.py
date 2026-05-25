"""Table `tickets` — métadonnées d'un ticket uploadé.

État (`status`) :
- `pending`    : Signed URL générée, attendant l'upload GCS effectif.
- `uploaded`   : objet présent dans GCS (déclencheur OCR).
- `ocr_done`   : worker OCR a terminé, articles dispo dans `prix_extraits`.
- `ocr_failed` : OCR a échoué (image illisible, modèle KO). Pas de retry auto.
- `validated`  : utilisateur a validé/corrigé les items.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base

TICKET_STATUSES = ("pending", "uploaded", "ocr_done", "ocr_failed", "validated")


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

    # Champs renseignés par le worker OCR — NULL tant que le ticket n'est pas traité.
    enseigne: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_ticket: Mapped[datetime.date | None] = mapped_column(nullable=True)
    total_eur: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(nullable=True)
    ocr_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
