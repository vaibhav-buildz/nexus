"""Pydantic schemas for Project request validation and responses."""

from datetime import datetime
import re
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateProjectRequest(BaseModel):
    """Payload to create a new project."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, description="Human-readable project name")
    slug: str = Field(min_length=1, max_length=128, description="URL-friendly unique project slug")
    description: str | None = Field(default=None, description="Optional project description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate project name: not empty or whitespace-only."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Project name cannot be empty or whitespace.")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Validate slug format: lowercase alphanumeric words separated by single hyphens."""
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", v):
            raise ValueError(
                "Slug must be lowercase alphanumeric with hyphens (e.g. 'e-commerce', 'payment-api')."
            )
        return v


class UpdateProjectRequest(BaseModel):
    """Payload to update permitted project fields."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128, description="Updated project name")
    slug: str | None = Field(default=None, min_length=1, max_length=128, description="Updated project slug")
    description: str | None = Field(default=None, description="Updated project description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate project name when provided: not empty or whitespace-only."""
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Project name cannot be empty or whitespace.")
            return cleaned
        return v

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        """Validate slug format when provided: lowercase alphanumeric with single hyphens."""
        if v is not None:
            if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", v):
                raise ValueError(
                    "Slug must be lowercase alphanumeric with hyphens (e.g. 'e-commerce', 'payment-api')."
                )
            return v
        return v


class ProjectResponse(BaseModel):
    """Public project response representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
