"""Pydantic schemas for authentication and identity endpoints."""

from datetime import datetime
import re
import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegisterRequest(BaseModel):
    """User registration payload."""

    email: EmailStr = Field(description="Unique email address")
    password: str = Field(min_length=8, max_length=128, description="Strong account password")

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Enforce password strength rules."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter.")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit.")
        return v


class UserLoginRequest(BaseModel):
    """User login credential payload."""

    email: EmailStr
    password: str = Field(min_length=1)


class TokenRefreshRequest(BaseModel):
    """Refresh token rotation request payload."""

    refresh_token: str = Field(min_length=1, description="Opaque refresh token string")


class TokenLogoutRequest(BaseModel):
    """Session revocation payload."""

    refresh_token: str = Field(min_length=1, description="Opaque refresh token string to revoke")


class VerifyEmailRequest(BaseModel):
    """Email verification payload."""

    token: str = Field(min_length=1, description="Verification token received via email")


class UserResponse(BaseModel):
    """Public user response entity."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    is_active: bool
    is_verified: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Authentication token response payload."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifespan in seconds")


class MessageResponse(BaseModel):
    """Generic status and message response."""

    message: str
    status: str = "ok"
