"""Reusable FastAPI dependencies for request authentication and context injection."""

from typing import Annotated
import logging
import uuid
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import (
    InactiveOrganizationError,
    InactiveUserError,
    InsufficientPermissionsError,
    InvalidTokenError,
    NotAnOrganizationMemberError,
    OrganizationNotFoundError,
)
from app.core.rbac import Permission, has_permission, validate_organization_membership
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

logger = logging.getLogger("nexus.deps")

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


async def get_organization_context(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Organization:
    """Resolve and validate active organization from URL path context /organizations/{org_id}/...

    Enforces uniform non-disclosure for unauthorized tenant access: a caller who is not a
    member of the organization receives HTTP 404 to prevent tenant existence enumeration.
    """
    if isinstance(org_id, str):
        try:
            org_id = uuid.UUID(org_id)
        except ValueError:
            raise OrganizationNotFoundError("Organization not found.")

    # 1. Verify caller membership first to prevent tenant enumeration
    membership = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == current_user.id,
        )
    )
    if not membership:
        raise OrganizationNotFoundError("Organization not found.")

    # 2. Verify organization exists and is active
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise OrganizationNotFoundError("Organization not found.")

    if not org.is_active:
        raise InactiveOrganizationError("Organization is inactive.")

    return org


async def get_current_org_membership(
    org: Annotated[Organization, Depends(get_organization_context)],
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationMember:
    """Ensure authenticated verified user is an active member of the target organization context."""
    membership = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == current_user.id,
        )
    )
    if not membership:
        raise OrganizationNotFoundError("Organization not found.")

    if not validate_organization_membership(membership.organization_id, org.id):
        raise OrganizationNotFoundError("Organization not found.")

    return membership


class RequirePermission:
    """Dependency callable validating that member's role possesses the required permission."""

    def __init__(self, permission: Permission | str) -> None:
        self.permission = Permission(permission) if isinstance(permission, str) else permission

    async def __call__(
        self,
        membership: Annotated[OrganizationMember, Depends(get_current_org_membership)],
    ) -> OrganizationMember:
        if not has_permission(membership.role, self.permission):
            logger.warning(
                "User %s (role: %s) denied permission %s in org %s",
                membership.user_id,
                membership.role,
                self.permission,
                membership.organization_id,
            )
            raise InsufficientPermissionsError("Insufficient permissions.")
        return membership


def require_permission(permission: Permission | str) -> RequirePermission:
    """Dependency factory creating permission enforcement for routes."""
    return RequirePermission(permission)
