"""Get-or-create user à partir du JWT Firebase.

Au premier appel authentifié d'un user, on crée la ligne `users` à la volée.
Cela évite un endpoint séparé `POST /users` et garantit qu'un user existant
dans Firebase Auth aura toujours une ligne SQL pour accrocher ses tickets.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthenticatedUser
from ..logging import get_logger
from ..models.users import User

logger = get_logger(__name__)


async def get_or_create_user(session: AsyncSession, auth_user: AuthenticatedUser) -> User:
    stmt = select(User).where(User.firebase_uid == auth_user.uid)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        firebase_uid=auth_user.uid,
        email=auth_user.email,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    logger.info("user_provisioned", firebase_uid=auth_user.uid, user_id=str(user.id))
    return user
