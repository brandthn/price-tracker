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
