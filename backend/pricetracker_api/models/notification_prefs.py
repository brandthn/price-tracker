"""Table `notification_prefs` — seuils d'alerte et préférences par utilisateur."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import ARRAY, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class NotificationPrefs(Base):
    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    threshold_pct: Mapped[float] = mapped_column(
        Numeric(5, 2),
        default=5.0,
        doc="Seuil de hausse en %. 5.0 = alerter au-delà de 5% de hausse.",
    )
    frequency: Mapped[str] = mapped_column(
        String(20), default="weekly", doc="weekly | biweekly | monthly"
    )
    favorite_enseignes: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(100)),
        nullable=True,
        doc="Enseignes à privilégier dans les recommandations de substituts.",
    )
    fcm_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True, doc="Token Firebase Cloud Messaging pour push."
    )

    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
