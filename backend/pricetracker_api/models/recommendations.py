"""Table `product_substitutions` — ORM SQLAlchemy 2.x.

Alimentée chaque nuit par le recalcul SQL (score composite :
économie 45 % · similarité cosine 35 % · qualité 20 %).
Les requêtes de lecture passent par du SQL brut via `text()` pour
pouvoir accéder aux vues matérialisées `product_metrics` et
`product_prices` sans les mapper en ORM.

L'embedding n'est jamais lu ici — le calcul de similarité est fait
au moment du recalcul nightly côté Cloud SQL (opérateur `<=>`).
"""
from __future__ import annotations

import datetime

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ProductSubstitution(Base):
    __tablename__ = "product_substitutions"

    source_ean: Mapped[str] = mapped_column(String(13), primary_key=True)
    target_ean: Mapped[str] = mapped_column(String(13), primary_key=True)

    # Score composite normalisé [0.0, 1.0]
    score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)

    # Économie absolue en € (peut être NULL si avg_price manquant)
    saving_avg: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)

    # Économie en % par rapport au prix source
    saving_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Similarité cosine brute [0.0, 1.0]
    similarity: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)

    computed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
