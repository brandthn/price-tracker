"""DTOs users + preferences."""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    firebase_uid: str
    email: str | None
    display_name: str | None
    departement: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    departement: str | None = Field(default=None, max_length=3)


class NotificationPrefsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    threshold_pct: float
    frequency: str
    favorite_enseignes: list[str] | None
    fcm_token: str | None


class NotificationPrefsPatch(BaseModel):
    threshold_pct: float | None = Field(default=None, ge=0, le=100)
    frequency: str | None = Field(default=None, pattern="^(weekly|biweekly|monthly)$")
    favorite_enseignes: list[str] | None = None
    fcm_token: str | None = Field(default=None, max_length=255)


class BasketMonth(BaseModel):
    """Dépenses d'un mois calendaire (tickets avec total lisible)."""

    month: datetime.date
    total_eur: float
    tickets: int


class BasketProduct(BaseModel):
    """Produit récurrent du panier (groupé par EAN, sinon par libellé)."""

    ean: str | None
    label: str
    purchases: int
    avg_price_eur: float | None
    last_purchased: datetime.date | None


class BasketSummaryOut(BaseModel):
    """Vue « Mon budget » : le panier réel de l'utilisateur, calculé depuis
    ses tickets (Cloud SQL). Les champs monétaires restent None tant
    qu'aucun ticket avec total lisible n'existe — le frontend affiche alors
    l'onboarding « ajoutez votre premier ticket »."""

    tickets_count: int
    total_spent_eur: float | None
    avg_ticket_eur: float | None
    first_ticket_date: datetime.date | None
    monthly: list[BasketMonth] = Field(default_factory=list)
    top_products: list[BasketProduct] = Field(default_factory=list)
