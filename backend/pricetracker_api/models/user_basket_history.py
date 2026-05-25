"""Table `user_basket_history` — agrégation des achats récurrents d'un user.

Alimentée par le worker indices (Phase 9) à partir des `prix_extraits`
validés sur 6 mois glissants. Sert au calcul de l'indice personnel et au
ciblage des alertes (« vos produits habituels »).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class UserBasketHistory(Base):
    __tablename__ = "user_basket_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ean: Mapped[str] = mapped_column(String(13), index=True)

    purchase_count_6m: Mapped[int] = mapped_column(default=0)
    avg_quantity: Mapped[float | None] = mapped_column(nullable=True)
    last_purchased_at: Mapped[datetime.date | None] = mapped_column(nullable=True)

    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "ean", name="user_basket_history_user_ean_uq"),
    )
