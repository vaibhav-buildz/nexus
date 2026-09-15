"""Application configuration module using Pydantic Settings."""

from functools import lru_cache
from typing import Literal
from pydantic import Field, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application Information
    PROJECT_NAME: str = "NEXUS"
    APP_ENV: Literal["development", "testing", "staging", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "json"

    # API Server
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_PREFIX: str = "/api/v1"

    # PostgreSQL Database Configuration
    POSTGRES_HOST: str = Field(default="localhost", description="Database host")
    POSTGRES_PORT: int = Field(default=5432, description="Database port")
    POSTGRES_USER: str = Field(default="nexus", description="Database user")
    POSTGRES_PASSWORD: str = Field(default="nexus_secret", description="Database password")
    POSTGRES_DB: str = Field(default="nexus_db", description="Database name")
    DATABASE_URL: str | None = Field(default=None, description="Direct database URL override if provided")

    # Connection Pool Settings
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False

    # Authentication & Security
    JWT_SECRET_KEY: str = Field(
        default="nexus-insecure-dev-secret-key-change-in-prod-minimum-32-chars",
        description="Cryptographic secret key for signing JWT tokens",
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, description="Access token lifetime in minutes")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="Refresh token lifetime in days")
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = Field(
        default=24, description="Email verification token validity in hours"
    )
    EMAIL_SERVICE_PROVIDER: Literal["console", "mock"] = Field(
        default="console", description="Email provider backend"
    )

    @computed_field
    @property
    def async_database_url(self) -> str:
        """Construct the async database connection URL for SQLAlchemy (asyncpg)."""
        if self.DATABASE_URL:
            # Normalize to asyncpg driver if scheme is postgresql://
            if self.DATABASE_URL.startswith("postgresql://"):
                return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field
    @property
    def sync_database_url(self) -> str:
        """Construct the sync database URL (useful for Alembic migrations or sync tools)."""
        if self.DATABASE_URL:
            if self.DATABASE_URL.startswith("postgresql+asyncpg://"):
                return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
            return self.DATABASE_URL
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()
