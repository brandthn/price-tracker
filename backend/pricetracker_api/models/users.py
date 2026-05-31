"""Table `users` — profil applicatif. Complète Firebase Auth (qui détient
l'authentification et le couple email/password). La PK est l'UID Firebase.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class User(Base):
    __tablename__ = "users"

    # firebase_uid : `sub` du JWT Firebase. Clé fonctionnelle (lookup à
    # chaque requête authentifiée). On garde aussi un UUID interne pour
    # référencer l'utilisateur depuis d'autres tables sans dépendre du
    # provider d'auth.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    departement: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
        doc="Code département FR (01-95, 2A, 2B, 971-976). Utilisé pour l'indice régional.",
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
