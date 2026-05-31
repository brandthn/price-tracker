"""SQLAlchemy ORM models.

Toutes les tables sont déclarées sur la même `Base` pour qu'Alembic
autogenerate les détecte. Le DDL de `products` est aligné avec celui
créé par le worker OFF (`workers/off/pricetracker_off/pg.py`) pour
qu'Alembic puisse le `CREATE TABLE IF NOT EXISTS`.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import des modèles pour qu'ils soient enregistrés sur Base.metadata.
from .notification_prefs import NotificationPrefs  # noqa: E402, F401
from .prix_extraits import PrixExtrait  # noqa: E402, F401
from .product_aliases import ProductAlias  # noqa: E402, F401
from .products import Product  # noqa: E402, F401
from .tickets import Ticket  # noqa: E402, F401
from .user_basket_history import UserBasketHistory  # noqa: E402, F401
from .users import User  # noqa: E402, F401
