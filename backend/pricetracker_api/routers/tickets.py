"""Router tickets — upload-url, list, get, patch items."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthenticatedUser, verify_bearer
from ..config import get_settings
from ..db import get_session
from ..gcs import generate_ticket_read_url, generate_ticket_upload_url
from ..logging import get_logger
from ..models.ocr_feedback import OcrFeedback
from ..models.prix_extraits import PrixExtrait
from ..models.product_aliases import ProductAlias
from ..models.tickets import Ticket
from ..schemas.tickets import (
    FeedbackRequest,
    FeedbackResponse,
    PrixExtraitOut,
    TicketDetailOut,
    TicketImageURLResponse,
    TicketItemsPatchRequest,
    TicketOut,
    TicketsListResponse,
    TicketUploadURLRequest,
    TicketUploadURLResponse,
)
from ..services import pubsub
from ..services.user_provisioning import get_or_create_user

logger = get_logger(__name__)
router = APIRouter(prefix="/tickets", tags=["tickets"])


def _line_paid_amount(item: PrixExtrait) -> float | None:
    # priorite : price_eur (correction user) > line_total (OCR) > unit_price*qty
    if item.price_eur is not None:
        return float(item.price_eur)
    if item.line_total is not None:
        return float(item.line_total)
    if item.unit_price is not None:
        qty = float(item.quantity) if item.quantity is not None else 1.0
        return float(item.unit_price) * qty
    return None


def _recompute_total(items: list[PrixExtrait]) -> float | None:
    amounts = [a for a in (_line_paid_amount(i) for i in items) if a is not None]
    return round(sum(amounts), 2) if amounts else None


@router.post(
    "/upload-url",
    response_model=TicketUploadURLResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_upload_url(
    body: TicketUploadURLRequest,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> TicketUploadURLResponse:
    """Signed URL V4 PUT pour l'upload d'un ticket."""
    # UUID reserve pour le nommage GCS ; ligne tickets en pending, transition
    # pending -> uploaded faite par le worker OCR (trigger OBJECT_FINALIZE)
    db_user = await get_or_create_user(session, user)
    ticket_id = uuid.uuid4()

    try:
        signed = await asyncio.to_thread(
            generate_ticket_upload_url,
            user_id=str(db_user.id),
            content_type=body.content_type,
            ticket_uuid=str(ticket_id),
        )
    except RuntimeError as exc:
        logger.error("signed_url_generation_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signed URL generation failed (check backend SA token creator role).",
        ) from exc

    ticket = Ticket(
        id=ticket_id,
        user_id=db_user.id,
        status="pending",
        gcs_path=signed.gcs_path,
    )
    session.add(ticket)
    await session.commit()

    return TicketUploadURLResponse(
        ticket_id=ticket_id,
        upload_url=signed.upload_url,
        gcs_path=signed.gcs_path,
        expires_at=signed.expires_at,
        content_type=signed.content_type,  # type: ignore[arg-type]
    )


@router.get("", response_model=TicketsListResponse)
async def list_my_tickets(
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> TicketsListResponse:
    db_user = await get_or_create_user(session, user)
    total = (
        await session.scalar(
            select(func.count()).select_from(Ticket).where(Ticket.user_id == db_user.id)
        )
    ) or 0
    rows = (
        await session.execute(
            select(Ticket)
            .where(Ticket.user_id == db_user.id)
            .order_by(Ticket.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return TicketsListResponse(
        items=[TicketOut.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/{ticket_id}", response_model=TicketDetailOut)
async def get_ticket(
    ticket_id: uuid.UUID,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> TicketDetailOut:
    db_user = await get_or_create_user(session, user)
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None or ticket.user_id != db_user.id:
        # 404 identique not-found / autre-user : pas de leak d'IDs
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found.")

    items = (
        await session.execute(
            select(PrixExtrait)
            .where(PrixExtrait.ticket_id == ticket.id)
            .order_by(PrixExtrait.line_index)
        )
    ).scalars().all()

    out = TicketDetailOut.model_validate(ticket)
    out.items = [PrixExtraitOut.model_validate(i) for i in items]
    return out


@router.get("/{ticket_id}/image-url", response_model=TicketImageURLResponse)
async def get_ticket_image_url(
    ticket_id: uuid.UUID,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> TicketImageURLResponse:
    """Signed URL GET de l'image du ticket."""
    db_user = await get_or_create_user(session, user)
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None or ticket.user_id != db_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    if not ticket.gcs_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket image not available.")

    try:
        signed = await asyncio.to_thread(generate_ticket_read_url, gcs_path=ticket.gcs_path)
    except (RuntimeError, ValueError) as exc:
        logger.error("signed_read_url_failed", ticket_id=str(ticket_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signed read URL generation failed.",
        ) from exc

    return TicketImageURLResponse(read_url=signed.read_url, expires_at=signed.expires_at)


@router.patch("/{ticket_id}/items", response_model=TicketDetailOut)
async def patch_ticket_items(
    ticket_id: uuid.UUID,
    body: TicketItemsPatchRequest,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> TicketDetailOut:
    """Validation/correction des items OCR par l'utilisateur."""
    # item patche -> validated_by_user=True ; ean/produit_nom fourni enrichit
    # product_aliases (raw_text, enseigne) -> ean pour le matching futur
    db_user = await get_or_create_user(session, user)
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None or ticket.user_id != db_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found.")

    item_ids = [p.id for p in body.items]
    rows = (
        await session.execute(
            select(PrixExtrait).where(
                PrixExtrait.ticket_id == ticket.id, PrixExtrait.id.in_(item_ids)
            )
        )
    ).scalars().all()
    if len(rows) != len(item_ids):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Some item ids don't belong to this ticket.",
        )
    by_id = {p.id: p for p in rows}

    for patch in body.items:
        item = by_id[patch.id]
        if patch.ean is not None:
            item.ean = patch.ean
        if patch.produit_nom is not None:
            item.produit_nom = patch.produit_nom
        if patch.quantity is not None:
            item.quantity = patch.quantity
        if patch.price_eur is not None:
            item.price_eur = patch.price_eur
        item.needs_validation = False
        item.validated_by_user = True

        # enseigne="" si NULL : la PK composite (raw_text, enseigne, source) refuse NULL
        if patch.ean:
            enseigne = ticket.enseigne or ""
            produit_nom = patch.produit_nom or item.produit_nom
            stmt = (
                pg_insert(ProductAlias)
                .values(
                    raw_text=item.raw_text,
                    enseigne=enseigne,
                    source="user-validation",
                    ean=patch.ean,
                    produit_nom=produit_nom,
                    confidence=1.0,
                    validated_by_user=True,
                )
                .on_conflict_do_update(
                    constraint="product_aliases_pk",
                    set_={
                        "ean": patch.ean,
                        "produit_nom": produit_nom,
                        "confidence": 1.0,
                        "validated_by_user": True,
                    },
                )
            )
            await session.execute(stmt)

    # recalcul total sur toutes les lignes (le select flush les corrections) ;
    # sinon total_eur reste fige a la valeur OCR
    items = (
        await session.execute(
            select(PrixExtrait)
            .where(PrixExtrait.ticket_id == ticket.id)
            .order_by(PrixExtrait.line_index)
        )
    ).scalars().all()
    ticket.total_eur = _recompute_total(list(items))
    ticket.status = "validated"
    await session.commit()

    await session.refresh(ticket)
    out = TicketDetailOut.model_validate(ticket)
    out.items = [PrixExtraitOut.model_validate(i) for i in items]
    return out


async def _load_ticket_detail(session: AsyncSession, ticket: Ticket) -> TicketDetailOut:
    items = (
        await session.execute(
            select(PrixExtrait)
            .where(PrixExtrait.ticket_id == ticket.id)
            .order_by(PrixExtrait.line_index)
        )
    ).scalars().all()
    out = TicketDetailOut.model_validate(ticket)
    out.items = [PrixExtraitOut.model_validate(i) for i in items]
    return out


@router.post("/{ticket_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    ticket_id: uuid.UUID,
    body: FeedbackRequest,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> FeedbackResponse:
    """Avis up/down sur l'output OCR."""
    # le ticket est deja compte ; ce feedback historise (ocr_feedback) et, si down,
    # relance un re-OCR tier-2 tant que ocr_attempts < prt_max_ocr_attempts
    db_user = await get_or_create_user(session, user)
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None or ticket.user_id != db_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found.")

    session.add(
        OcrFeedback(
            ticket_id=ticket.id,
            user_id=db_user.id,
            rating=body.rating,
            ocr_attempt=ticket.ocr_attempts,
            ocr_engine=ticket.ocr_model or ticket.ocr_engine,
        )
    )
    ticket.last_feedback = body.rating

    settings = get_settings()
    # escalade routee par le moteur du dernier OCR ; chaine bornee par
    # prt_max_ocr_attempts, engine hors map n'escalade pas
    next_topic: str | None = None
    if body.rating == "down" and ticket.ocr_attempts < settings.prt_max_ocr_attempts:
        next_topic = settings.ocr_escalation_by_engine.get(ticket.ocr_engine or "")
    retry_triggered = next_topic is not None

    await session.commit()
    await session.refresh(ticket)

    # publication apres commit : re-OCR seulement si l'avis est persiste.
    # echec publish -> 502, le feedback reste sauve
    if next_topic is not None:
        try:
            await asyncio.to_thread(pubsub.publish_to_topic, next_topic, str(ticket.id))
        except Exception as exc:
            logger.error(
                "ocr_escalation_publish_failed",
                ticket_id=str(ticket.id),
                topic=next_topic,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Feedback enregistré mais l'escalade OCR n'a pas pu être déclenchée.",
            ) from exc

    detail = await _load_ticket_detail(session, ticket)
    logger.info(
        "ticket_feedback",
        ticket_id=str(ticket.id),
        rating=body.rating,
        ocr_attempt=ticket.ocr_attempts,
        from_engine=ticket.ocr_engine,
        escalated_to=next_topic,
        retry_triggered=retry_triggered,
    )
    return FeedbackResponse(ticket=detail, retry_triggered=retry_triggered)
