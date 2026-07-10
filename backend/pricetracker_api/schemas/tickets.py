"""DTOs tickets + upload-url."""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ContentType = Literal["image/jpeg", "image/png"]


class TicketUploadURLRequest(BaseModel):
    content_type: ContentType = Field(
        default="image/jpeg",
        description="MIME type de l'image. Doit matcher exactement le Content-Type du PUT.",
    )


class TicketUploadURLResponse(BaseModel):
    ticket_id: uuid.UUID
    upload_url: str
    gcs_path: str
    expires_at: datetime.datetime
    content_type: ContentType


class TicketImageURLResponse(BaseModel):
    read_url: str
    expires_at: datetime.datetime


class PrixExtraitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    line_index: int
    raw_text: str
    ean: str | None
    produit_nom: str | None
    quantity: float | None
    unit_price: float | None
    line_total: float | None
    price_eur: float | None
    match_method: str | None
    ocr_confidence: float | None
    match_confidence: float | None
    needs_validation: bool
    validated_by_user: bool


FeedbackRating = Literal["up", "down"]


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    enseigne: str | None
    date_ticket: datetime.date | None
    total_eur: float | None
    ocr_confidence: float | None
    ocr_engine: str | None
    ocr_model: str | None
    ocr_duration_ms: int | None
    ocr_error: str | None
    ocr_attempts: int
    last_feedback: FeedbackRating | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class TicketDetailOut(TicketOut):
    items: list[PrixExtraitOut] = Field(default_factory=list)


class TicketItemPatch(BaseModel):
    """Correction d'une ligne par l'utilisateur."""

    id: uuid.UUID
    ean: str | None = Field(default=None, max_length=13)
    produit_nom: str | None = Field(default=None, max_length=300)
    quantity: float | None = Field(default=None, ge=0)
    price_eur: float | None = Field(default=None, ge=0)


class TicketItemsPatchRequest(BaseModel):
    items: list[TicketItemPatch]


class TicketsListResponse(BaseModel):
    items: list[TicketOut]
    total: int
    limit: int
    offset: int


class FeedbackRequest(BaseModel):
    """Avis 👍/👎 de l'utilisateur sur l'output OCR d'un ticket."""

    rating: FeedbackRating


class FeedbackResponse(BaseModel):
    """Renvoyé après un feedback : ticket à jour + indication de re-OCR lancé."""

    ticket: TicketDetailOut
    retry_triggered: bool = Field(
        default=False,
        description="True si un 👎 a déclenché un re-OCR tier-2 (sinon plafond atteint / 👍).",
    )
