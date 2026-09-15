"""Reusable FastAPI dependencies for request authentication and context injection."""

from typing import Annotated
import uuid
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import InactiveUserError, InvalidTokenError
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=True,
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Validate Bearer access token and return the authenticated active user."""
    payload = decode_access_token(token)
    user_id_str = payload.get("sub")

    if not user_id_str:
        raise InvalidTokenError("Token payload missing subject identifier.")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise InvalidTokenError("Malformed subject UUID in token payload.")

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise InvalidTokenError("Authenticated user does not exist.")

    if not user.is_active:
        raise InactiveUserError("User account is disabled.")

    return user


async def get_current_verified_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Ensure that the authenticated user has verified their email address."""
    if not current_user.is_verified:
        raise InactiveUserError("Email address has not been verified.")
    return current_user
