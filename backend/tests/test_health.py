"""Integration tests for health and readiness endpoints."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db_session
from app.main import create_application


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    """Verify GET /health returns 200 with service info."""
    response = await client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "NEXUS"
    assert "environment" in data


@pytest.mark.asyncio
async def test_database_health_endpoint_healthy(client: AsyncClient) -> None:
    """Verify GET /health/db returns 200 when database query succeeds."""
    response = await client.get("/health/db")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "latency_ms" in data
    assert isinstance(data["latency_ms"], (int, float))


@pytest.mark.asyncio
async def test_database_health_endpoint_failure() -> None:
    """Verify GET /health/db returns 503 when the database query fails."""
    app = create_application()

    # Create a mock session whose execute() method simulates a database failure
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute.side_effect = ConnectionRefusedError("Database connection lost")

    async def mock_failing_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db_session] = mock_failing_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health/db")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["database"] == "disconnected"
    assert "Database connection lost" in data["error"]
