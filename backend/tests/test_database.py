"""Tests for database connection behavior and verification."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import close_engine, get_engine, verify_database_connection


@pytest.mark.asyncio
async def test_verify_database_connection(test_db_session: AsyncSession) -> None:
    """Verify that verify_database_connection executes SELECT 1 and returns stats."""
    result = await verify_database_connection(test_db_session)
    assert result["status"] == "connected"
    assert "latency_ms" in result
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_engine_creation_and_disposal() -> None:
    """Verify that get_engine returns an engine and close_engine disposes cleanly."""
    engine = get_engine()
    assert engine is not None
    await close_engine()
