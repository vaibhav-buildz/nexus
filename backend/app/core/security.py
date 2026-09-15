"""Cryptographic security utilities for authentication, hashing, and token handling."""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import jwt
from app.core.config import get_settings
from app.core.errors import InvalidTokenError

# Argon2id password hasher with OWASP-recommended parameters
_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Hash password string using Argon2id."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against Argon2id hash using constant-time comparison."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, Exception):
        return False


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Generate a signed short-lived JWT access token."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "iss": settings.PROJECT_NAME,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate signature/expiration of a JWT access token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.PROJECT_NAME,
            options={"require": ["sub", "exp", "iat"]},
        )
        if payload.get("type") != "access":
            raise InvalidTokenError("Invalid token type; expected access token.")
        return payload
    except jwt.ExpiredSignatureError:
        raise InvalidTokenError("Access token has expired.")
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(f"Token validation failed: {str(exc)}")


def generate_secure_random_token(nbytes: int = 32) -> str:
    """Generate cryptographically secure random urlsafe string for refresh/verification tokens."""
    return secrets.token_urlsafe(nbytes)


def hash_token(raw_token: str) -> str:
    """Compute SHA-256 hex digest of a token for safe persistence in database."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
