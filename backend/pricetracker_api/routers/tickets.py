"""Router tickets — upload-url, list, get, patch items."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthenticatedUser, verify_bearer
from ..db import get_session
from ..gcs import generate_ticket_upload_url
from ..logging import get_logger
from ..models.prix_extraits import PrixExtrait
from ..models.product_aliases import ProductAlias
from ..models.tickets import Ticket
from ..schemas.tickets import (
    PrixExtraitOut,
    TicketDetailOut,
    TicketItemsPatchRequest,
    TicketOut,
    TicketsListResponse,
    TicketUploadURLRequest,
    TicketUploadURLResponse,
)
from ..services.user_provisioning import get_or_create_user

logger = get_logger(__name__)
router = APIRouter(prefix="/tickets", tags=["tickets"])


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
    """Génère une Signed URL V4 PUT pour l'upload d'un ticket.

    1. (lazy) crée la ligne `users` si premier appel.
    2. Pré-réserve un UUID de ticket pour le nommage GCS.
    3. Signe l'URL (TTL configurable, défaut 15 min).
    4. Insère la ligne `tickets` en statut `pending` + `gcs_path` reflétant
       l'URL signée. La transition `pending → uploaded` est faite par le
       worker OCR lors du déclencheur Pub/Sub `OBJECT_FINALIZE`.
    """
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
        # Mêmes 404 pour "non trouvé" et "appartient à un autre user" pour
        # éviter de leaker l'existence d'IDs d'autres comptes.
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


@router.patch("/{ticket_id}/items", response_model=TicketDetailOut)
async def patch_ticket_items(
    ticket_id: uuid.UUID,
    body: TicketItemsPatchRequest,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> TicketDetailOut:
    """Validation/correction des items OCR par l'utilisateur.

    Chaque item patché passe à `validated_by_user=True`. Si un `ean` ou
    `produit_nom` est fourni, on enrichit `product_aliases` avec la paire
    (raw_text, enseigne) → ean pour améliorer le matching futur (boucle de
    feedback).
    """
    db_user = await get_or_create_user(session, user)
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None or ticket.user_id != db_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found.")

    # Charge tous les items concernés en une requête.
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

        # Feedback loop : insert/update product_aliases pour réutilisation OCR future.
        # Enseigne="" si NULL côté ticket : la PK composite (raw_text, enseigne, source)
        # n'accepte pas de NULL.
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

    ticket.status = "validated"
    await session.commit()

    items = (
        await session.execute(
            select(PrixExtrait)
            .where(PrixExtrait.ticket_id == ticket.id)
            .order_by(PrixExtrait.line_index)
        )
    ).scalars().all()
    await session.refresh(ticket)
    out = TicketDetailOut.model_validate(ticket)
    out.items = [PrixExtraitOut.model_validate(i) for i in items]
    return out
