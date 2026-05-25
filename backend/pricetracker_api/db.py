"""SQLAlchemy 2.x async + asyncpg — session dependency FastAPI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings
from .logging import get_logger

logger = get_logger(__name__)

_engine: Any = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    """Crée le moteur SQLAlchemy au démarrage de l'app (lifespan).

    `pool_pre_ping=True` : asyncpg ne reconnecte pas auto après un timeout
    Cloud SQL (idle 10 min). Le ping ajoute un coût négligeable (1ms) mais
    évite les `InterfaceError` lors du premier query après scale-from-zero.
    """
    global _engine, _session_factory
    settings = get_settings()
    _engine = create_async_engine(
        settings.database_url,
        pool_size=settings.prt_pg_pool_size,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
    )
    _session_factory = async_sessionmaker(
        _engine, expire_on_commit=False, class_=AsyncSession
    )
    logger.info(
        "db_engine_initialized",
        host=settings.prt_pg_host,
        db=settings.prt_pg_db,
        pool_size=settings.prt_pg_pool_size,
    )


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency FastAPI : yield une AsyncSession scoped à la requête.

    Rollback automatique sur exception. Le commit doit être explicite dans
    le router (ou en service) — pas de commit auto à la fin pour éviter de
    masquer des erreurs de logique métier.
    """
    if _session_factory is None:
        raise RuntimeError("Session factory not initialized — call init_engine() first.")
    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
