"""Pydantic schemas for Environment request validation and responses."""

from datetime import datetime
import re
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateEnvironmentRequest(BaseModel):
    """Payload to create a new environment."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, description="Human-readable environment name")
    slug: str = Field(min_length=1, max_length=64, description="URL-friendly unique environment slug")
    description: str | None = Field(default=None, max_length=500, description="Optional environment description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate environment name: not empty or whitespace-only."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Environment name cannot be empty or whitespace.")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Validate slug format: lowercase alphanumeric words separated by single hyphens."""
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", v):
            raise ValueError(
                "Slug must be lowercase alphanumeric with hyphens (e.g. 'development', 'staging', 'production')."
            )
        return v


class UpdateEnvironmentRequest(BaseModel):
    """Payload to update permitted environment fields."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128, description="Updated environment name")
    slug: str | None = Field(default=None, min_length=1, max_length=64, description="Updated environment slug")
    description: str | None = Field(default=None, max_length=500, description="Updated environment description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate environment name when provided: not empty or whitespace-only."""
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Environment name cannot be empty or whitespace.")
            return cleaned
        return v

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        """Validate slug format when provided: lowercase alphanumeric with single hyphens."""
        if v is not None:
            if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", v):
                raise ValueError(
                    "Slug must be lowercase alphanumeric with hyphens (e.g. 'development', 'staging', 'production')."
                )
            return v
        return v


class EnvironmentResponse(BaseModel):
    """Public environment response representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
