"""Unit tests for configuration management."""

import pytest
from app.core.config import Settings


def test_default_settings() -> None:
    """Verify default settings values when no environment overrides are provided."""
    settings = Settings(
        POSTGRES_USER="test_user",
        POSTGRES_PASSWORD="test_password",
        POSTGRES_HOST="db.internal",
        POSTGRES_PORT=5432,
        POSTGRES_DB="test_nexus",
    )

    assert settings.PROJECT_NAME == "NEXUS"
    assert settings.POSTGRES_HOST == "db.internal"
    assert settings.POSTGRES_PORT == 5432
    assert settings.POSTGRES_DB == "test_nexus"
    assert settings.async_database_url == "postgresql+asyncpg://test_user:test_password@db.internal:5432/test_nexus"
    assert settings.sync_database_url == "postgresql://test_user:test_password@db.internal:5432/test_nexus"


def test_database_url_override() -> None:
    """Verify explicit DATABASE_URL overrides individual connection parameters."""
    custom_url = "postgresql://prod_user:secret@postgres.cluster:5432/production_nexus"
    settings = Settings(DATABASE_URL=custom_url)

    assert settings.sync_database_url == custom_url
    assert settings.async_database_url == "postgresql+asyncpg://prod_user:secret@postgres.cluster:5432/production_nexus"


def test_log_level_validation() -> None:
    """Verify invalid log level raises validation error."""
    with pytest.raises(Exception):
        Settings(LOG_LEVEL="INVALID_LEVEL")
