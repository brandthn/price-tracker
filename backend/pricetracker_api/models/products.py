"""Table `products` — DDL aligné sur celui créé par le worker OFF.

Source de vérité : `workers/off/pricetracker_off/pg.py` (DDL embarqué pour
bootstrap). Le worker OFF écrit en `INSERT … ON CONFLICT (ean) DO UPDATE`
les EANs enrichis via OpenFoodFacts ; les colonnes optionnelles peuvent
être NULL pour les EAN non trouvés (`off_found=False`).

⚠️ Si on modifie ce DDL, modifier aussi `workers/off/pricetracker_off/pg.py`
et coordonner via une migration Alembic.

L'embedding est en `vector(768)` (pgvector). Le type pgvector n'a pas de
binding SQLAlchemy natif dans cette stack — on déclare la colonne en
`String` côté Python pour pouvoir lire la table, mais les requêtes de
similarité passent par du SQL brut (ORDER BY embedding <=> $1::vector).
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class Product(Base):
    __tablename__ = "products"

    ean: Mapped[str] = mapped_column(String(13), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_l3: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    nutriscore: Mapped[str | None] = mapped_column(String(1), nullable=True)
    nova: Mapped[str | None] = mapped_column(String(1), nullable=True)
    ecoscore: Mapped[str | None] = mapped_column(String(1), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    off_found: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # `embedding` reste un blob côté ORM (le SDK pgvector officiel n'est pas
    # installé). Les requêtes de similarité utilisent du raw SQL.
    # On expose le type via `info` pour qu'Alembic émette `vector(768)` dans
    # la migration (cf. alembic/versions/0001_init.py).
    enriched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )
    source: Mapped[str | None] = mapped_column(String(50), nullable=True, default="openfoodfacts")
