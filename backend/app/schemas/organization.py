"""Pydantic schemas for organization request validation and responses."""

from datetime import datetime
import re
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationCreateRequest(BaseModel):
    """Payload to create a new organization."""

    name: str = Field(min_length=1, max_length=128, description="Human-readable organization name")
    slug: str = Field(min_length=1, max_length=128, description="URL-friendly unique organization slug")
    description: str | None = Field(default=None, description="Optional organization description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate organization name: not empty or whitespace."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Organization name cannot be empty or whitespace.")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """Validate slug format: lowercase alphanumeric with hyphens."""
        cleaned = v.strip().lower()
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", cleaned):
            raise ValueError("Slug must be lowercase alphanumeric with hyphens (e.g. 'acme-corp').")
        return cleaned


class OrganizationUpdateRequest(BaseModel):
    """Payload to update permitted organization metadata fields."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128, description="Updated organization name")
    description: str | None = Field(default=None, description="Updated organization description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        """Validate organization name: not empty or whitespace when provided."""
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Organization name cannot be empty or whitespace.")
            return cleaned
        return v


class OrganizationResponse(BaseModel):
    """Public organization response entity."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
