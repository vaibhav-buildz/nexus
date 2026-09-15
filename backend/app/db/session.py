"""SQLAlchemy async engine and session management."""

import time
import logging
from collections.abc import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.core.config import get_settings

logger = logging.getLogger("nexus.db")

_async_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or initialize the singleton SQLAlchemy AsyncEngine."""
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        engine_kwargs = {
            "echo": settings.DB_ECHO,
            "future": True,
        }
        # SQLite in-memory (used in some test scenarios) doesn't use pool_size/max_overflow
        if not settings.async_database_url.startswith("sqlite"):
            engine_kwargs.update(
                {
                    "pool_size": settings.DB_POOL_SIZE,
                    "max_overflow": settings.DB_MAX_OVERFLOW,
                    "pool_timeout": settings.DB_POOL_TIMEOUT,
                    "pool_pre_ping": True,
                }
            )

        _async_engine = create_async_engine(settings.async_database_url, **engine_kwargs)
        logger.info(
            "SQLAlchemy AsyncEngine created",
            extra={"database_host": settings.POSTGRES_HOST, "database_name": settings.POSTGRES_DB},
        )
    return _async_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or initialize the sessionmaker for creating AsyncSession instances."""
    global _async_session_factory
    if _async_session_factory is None:
        engine = get_engine()
        _async_session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )
    return _async_session_factory


# For backwards compatibility / direct import
def async_session_factory() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


async def close_engine() -> None:
    """Gracefully close and dispose the database connection pool."""
    global _async_engine, _async_session_factory
    if _async_engine is not None:
        logger.info("Disposing SQLAlchemy database engine...")
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None
        logger.info("SQLAlchemy database engine disposed.")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an AsyncSession."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def verify_database_connection(session: AsyncSession) -> dict[str, float | str]:
    """Execute a verification query to ensure PostgreSQL is reachable."""
    start_time = time.perf_counter()
    result = await session.execute(text("SELECT 1"))
    scalar_value = result.scalar()
    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    if scalar_value != 1:
        raise ValueError(f"Unexpected database verification query output: {scalar_value}")

    return {
        "status": "connected",
        "latency_ms": latency_ms,
    }
