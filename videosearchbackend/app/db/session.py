"""Async engine, session factory and the FastAPI session dependency."""

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Created eagerly but connects lazily — importing the app never touches the
# database, which keeps the test suite runnable without Postgres.
engine: AsyncEngine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=settings.app_debug,
)

SessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a session per request, rolling back if the handler raises."""
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ping() -> bool:
    """Best-effort connectivity check used at startup for a clear log line."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - depends on the environment
        logger.warning("Database unreachable at startup: %s", exc)
        return False


async def dispose() -> None:
    """Close pooled connections on shutdown."""
    await engine.dispose()
