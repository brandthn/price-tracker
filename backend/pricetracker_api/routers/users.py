"""Router users — /me + /me/preferences."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthenticatedUser, verify_bearer
from ..db import get_session
from ..models.notification_prefs import NotificationPrefs
from ..schemas.users import (
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
