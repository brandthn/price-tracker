"""SQLAlchemy ORM models.

Meme Base pour qu'Alembic autogenerate detecte les tables. DDL products aligne
sur celui du worker OFF (workers/off/pricetracker_off/pg.py).
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# enregistre les modeles sur Base.metadata
from .notification_prefs import NotificationPrefs  # noqa: E402, F401
from .ocr_feedback import OcrFeedback  # noqa: E402, F401
from .prix_extraits import PrixExtrait  # noqa: E402, F401
from .product_aliases import ProductAlias  # noqa: E402, F401
from .products import Product  # noqa: E402, F401
from .tickets import Ticket  # noqa: E402, F401
from .user_basket_history import UserBasketHistory  # noqa: E402, F401
from .users import User  # noqa: E402, F401
