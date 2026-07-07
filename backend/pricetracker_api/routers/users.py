"""Router users — /me + /me/preferences."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthenticatedUser, verify_bearer
from ..db import get_session
from ..models.notification_prefs import NotificationPrefs
from ..schemas.users import (
    BasketMonth,
    BasketProduct,
    BasketSummaryOut,
    NotificationPrefsOut,
    NotificationPrefsPatch,
    UserOut,
    UserPatch,
)
from ..services.user_provisioning import get_or_create_user

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    db_user = await get_or_create_user(session, user)
    return UserOut.model_validate(db_user)


@router.patch("/me", response_model=UserOut)
async def patch_me(
    body: UserPatch,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    db_user = await get_or_create_user(session, user)
    if body.display_name is not None:
        db_user.display_name = body.display_name
    if body.departement is not None:
        # Validation minimale : 2 ou 3 chars (FR métropole + DOM).
        dept = body.departement.upper()
        if len(dept) not in (2, 3):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Invalid département code.",
            )
        db_user.departement = dept
    await session.commit()
    await session.refresh(db_user)
    return UserOut.model_validate(db_user)


@router.get("/me/basket", response_model=BasketSummaryOut)
async def get_my_basket(
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> BasketSummaryOut:
    """Panier réel de l'utilisateur, agrégé depuis ses tickets (Cloud SQL).

    C'est la source de vérité de la vue « Mon budget » : dépenses mensuelles,
    panier moyen, produits récurrents. La date de référence d'un ticket est
    `date_ticket` (lue sur le ticket) avec repli sur `created_at` quand
    l'extraction n'a pas trouvé de date.
    """
    db_user = await get_or_create_user(session, user)
    uid = {"uid": db_user.id}

    summary = (
        await session.execute(
            text(
                """
                SELECT
                  COUNT(*) AS tickets_count,
                  SUM(total_eur) AS total_spent_eur,
                  AVG(total_eur) AS avg_ticket_eur,
                  MIN(COALESCE(date_ticket, created_at::date)) AS first_ticket_date
                FROM tickets
                WHERE user_id = :uid
                """
            ),
            uid,
        )
    ).mappings().one()

    monthly_rows = (
        await session.execute(
            text(
                """
                SELECT
                  date_trunc('month', COALESCE(date_ticket, created_at::date))::date AS month,
                  SUM(total_eur) AS total_eur,
                  COUNT(*) AS tickets
                FROM tickets
                WHERE user_id = :uid AND total_eur IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """
            ),
            uid,
        )
    ).mappings().all()

    # Produits récurrents : groupés par EAN quand il est résolu, sinon par
    # libellé normalisé — un même produit mal OCRisé ne compte qu'une fois.
    top_rows = (
        await session.execute(
            text(
                """
                SELECT
                  MIN(p.ean) AS ean,
                  MIN(COALESCE(p.produit_nom, p.raw_text)) AS label,
                  COUNT(*) AS purchases,
                  AVG(p.price_eur) AS avg_price_eur,
                  MAX(COALESCE(t.date_ticket, t.created_at::date)) AS last_purchased
                FROM prix_extraits p
                JOIN tickets t ON t.id = p.ticket_id
                WHERE t.user_id = :uid
                GROUP BY COALESCE(p.ean, lower(COALESCE(p.produit_nom, p.raw_text)))
                ORDER BY COUNT(*) DESC,
                         MAX(COALESCE(t.date_ticket, t.created_at::date)) DESC
                LIMIT 8
                """
            ),
            uid,
        )
    ).mappings().all()

    return BasketSummaryOut(
        tickets_count=int(summary["tickets_count"] or 0),
        total_spent_eur=(
            float(summary["total_spent_eur"]) if summary["total_spent_eur"] is not None else None
        ),
        avg_ticket_eur=(
            float(summary["avg_ticket_eur"]) if summary["avg_ticket_eur"] is not None else None
        ),
        first_ticket_date=summary["first_ticket_date"],
        monthly=[
            BasketMonth(
                month=r["month"],
                total_eur=float(r["total_eur"]),
                tickets=int(r["tickets"]),
            )
            for r in monthly_rows
        ],
        top_products=[
            BasketProduct(
                ean=r["ean"],
                label=r["label"],
                purchases=int(r["purchases"]),
                avg_price_eur=(
                    float(r["avg_price_eur"]) if r["avg_price_eur"] is not None else None
                ),
                last_purchased=r["last_purchased"],
            )
            for r in top_rows
        ],
    )


@router.get("/me/preferences", response_model=NotificationPrefsOut)
async def get_prefs(
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> NotificationPrefsOut:
    db_user = await get_or_create_user(session, user)
    prefs = await session.get(NotificationPrefs, db_user.id)
    if prefs is None:
        # Renvoie un payload de défauts plutôt que 404 : la ligne sera créée
        # au premier PATCH. C'est plus utile pour le frontend qui peut
        # afficher les défauts sans avoir à gérer le 404.
        return NotificationPrefsOut(
            threshold_pct=5.0,
            frequency="weekly",
            favorite_enseignes=None,
            fcm_token=None,
        )
    return NotificationPrefsOut.model_validate(prefs)


@router.patch("/me/preferences", response_model=NotificationPrefsOut)
async def patch_prefs(
    body: NotificationPrefsPatch,
    user: AuthenticatedUser = Depends(verify_bearer),
    session: AsyncSession = Depends(get_session),
) -> NotificationPrefsOut:
    db_user = await get_or_create_user(session, user)
    patch_values: dict[str, object] = {}
    if body.threshold_pct is not None:
        patch_values["threshold_pct"] = body.threshold_pct
    if body.frequency is not None:
        patch_values["frequency"] = body.frequency
    if body.favorite_enseignes is not None:
        patch_values["favorite_enseignes"] = body.favorite_enseignes
    if body.fcm_token is not None:
        patch_values["fcm_token"] = body.fcm_token

    insert_values = {"user_id": db_user.id, **patch_values}
    stmt = pg_insert(NotificationPrefs).values(**insert_values)
    if patch_values:
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"], set_=patch_values
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id"])
    await session.execute(stmt)
    await session.commit()

    prefs = await session.get(NotificationPrefs, db_user.id)
    assert prefs is not None
    return NotificationPrefsOut.model_validate(prefs)
