"""Pydantic schemas for organization membership endpoints."""

from datetime import datetime
import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from app.core.rbac import OrgRole


class MemberAddRequest(BaseModel):
    """Payload to add an existing registered user to an organization."""

    user_id: uuid.UUID | None = Field(default=None, description="Target user ID")
    email: EmailStr | None = Field(default=None, description="Target user email address")
    role: OrgRole = Field(default=OrgRole.MEMBER, description="Initial organization role")

    @model_validator(mode="after")
    def validate_user_identifier(self) -> "MemberAddRequest":
        """Ensure either user_id or email is provided."""
        if not self.user_id and not self.email:
            raise ValueError("Either 'user_id' or 'email' must be provided.")
        return self


class MemberRoleUpdateRequest(BaseModel):
    """Payload to change a member's role."""

    role: OrgRole = Field(description="New assigned organization role")


class MemberResponse(BaseModel):
    """Public organization member representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    email: EmailStr | None = None
    created_at: datetime
    updated_at: datetime
