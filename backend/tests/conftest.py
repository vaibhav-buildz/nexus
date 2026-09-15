"""Pytest test configuration and fixtures using real PostgreSQL integration database."""

import os
from collections.abc import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Test environment configuration targeting real PostgreSQL test database
os.environ["APP_ENV"] = "testing"
os.environ["POSTGRES_DB"] = "nexus_test_db"
os.environ["POSTGRES_USER"] = "nexus"
os.environ["POSTGRES_PASSWORD"] = "nexus_secret"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["EMAIL_SERVICE_PROVIDER"] = "mock"
os.environ["JWT_SECRET_KEY"] = "nexus-test-secret-key-for-testing-only-min-32-chars"

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_application
from app.services.email_service import MockEmailService, get_email_service

TEST_PG_URL = "postgresql+asyncpg://nexus:nexus_secret@localhost:5432/nexus_test_db"


@pytest.fixture
def test_settings() -> Settings:
    """Return testing settings."""
    return get_settings()


@pytest_asyncio.fixture
async def pg_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a per-test PostgreSQL async engine with NullPool to prevent event-loop conflicts on Windows."""
    engine = create_async_engine(
        TEST_PG_URL,
        echo=False,
        future=True,
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE email_verification_tokens, sessions, users CASCADE;"))
    await engine.dispose()


@pytest_asyncio.fixture
async def test_db_session(pg_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated database session bound to the test engine."""
    session_factory = async_sessionmaker(
        bind=pg_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def mock_email_service() -> MockEmailService:
    """Provide an isolated mock email service instance."""
    return MockEmailService()


@pytest_asyncio.fixture
async def client(
    test_db_session: AsyncSession,
    mock_email_service: MockEmailService,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTPX AsyncClient wired with live PostgreSQL test session."""
    app = create_application()

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield test_db_session

    def override_get_email_service() -> MockEmailService:
        return mock_email_service

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_email_service] = override_get_email_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
