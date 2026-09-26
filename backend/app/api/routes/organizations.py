"""Organization API route handlers for multi-tenant management."""

from typing import Annotated
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_verified_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.member import (
    MemberAddRequest,
    MemberResponse,
    MemberRoleUpdateRequest,
)
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
from app.services.membership_service import MembershipService
from app.services.organization_service import OrganizationService

router = APIRouter(tags=["Organizations"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=OrganizationResponse,
    summary="Create a new organization workspace",
)
async def create_organization(
    payload: OrganizationCreateRequest,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationResponse:
    """Create a new organization and assign the creator as OWNER in a single atomic transaction."""
    org = await OrganizationService.create_organization(
        db=db,
        creator=current_user,
        payload=payload,
    )
    return OrganizationResponse.model_validate(org)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=list[OrganizationResponse],
    summary="List all organizations the user belongs to",
)
async def list_organizations(
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[OrganizationResponse]:
    """Return all organizations where the current user has an active membership."""
    orgs = await OrganizationService.list_user_organizations(
        db=db,
        user=current_user,
    )
    return [OrganizationResponse.model_validate(org) for org in orgs]


@router.get(
    "/{org_id}",
    status_code=status.HTTP_200_OK,
    response_model=OrganizationResponse,
    summary="Get organization details",
)
async def get_organization(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationResponse:
    """Retrieve organization metadata for a member (requires org:read permission).

    A non-member receives a 404 Not Found response to prevent tenant existence discovery.
    """
    org = await OrganizationService.get_organization_for_user(
        db=db,
        user=current_user,
        org_id=org_id,
    )
    return OrganizationResponse.model_validate(org)


@router.patch(
    "/{org_id}",
    status_code=status.HTTP_200_OK,
    response_model=OrganizationResponse,
    summary="Update organization metadata",
)
async def update_organization(
    org_id: uuid.UUID,
    payload: OrganizationUpdateRequest,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationResponse:
    """Update permitted fields for an active organization (requires org:update permission)."""
    org = await OrganizationService.update_organization(
        db=db,
        user=current_user,
        org_id=org_id,
        payload=payload,
    )
    return OrganizationResponse.model_validate(org)


@router.delete(
    "/{org_id}",
    status_code=status.HTTP_200_OK,
    response_model=OrganizationResponse,
    summary="Deactivate an organization",
)
async def delete_organization(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationResponse:
    """Safely deactivate an organization by setting is_active=False (restricted to OWNER only).

    Destructive cascading deletion is omitted for data protection.
    """
    org = await OrganizationService.deactivate_organization(
        db=db,
        user=current_user,
        org_id=org_id,
    )
    return OrganizationResponse.model_validate(org)


# =========================================================================
# Membership Management Endpoints
# =========================================================================


@router.get(
    "/{org_id}/members",
    status_code=status.HTTP_200_OK,
    response_model=list[MemberResponse],
    summary="List organization members",
)
async def list_members(
    org_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[MemberResponse]:
    """Return all members belonging strictly to the requested organization context (requires member:read)."""
    return await MembershipService.list_members(
        db=db,
        current_user=current_user,
        org_id=org_id,
    )


@router.post(
    "/{org_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=MemberResponse,
    summary="Add an existing user to the organization",
)
async def add_member(
    org_id: uuid.UUID,
    payload: MemberAddRequest,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemberResponse:
    """Add a registered user to the organization with assigned role (requires member:invite)."""
    return await MembershipService.add_member(
        db=db,
        current_user=current_user,
        org_id=org_id,
        payload=payload,
    )


@router.patch(
    "/{org_id}/members/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=MemberResponse,
    summary="Update a member's role",
)
async def update_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberRoleUpdateRequest,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemberResponse:
    """Update a member's assigned role with explicit RBAC governance checks (requires member:role_update)."""
    return await MembershipService.update_member_role(
        db=db,
        current_user=current_user,
        org_id=org_id,
        target_user_id=user_id,
        new_role=payload.role,
    )


@router.delete(
    "/{org_id}/members/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponse,
    summary="Remove a member or self-leave from organization",
)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MessageResponse:
    """Remove a member or self-leave, enforcing sole-owner protection (requires member:remove)."""
    await MembershipService.remove_member(
        db=db,
        current_user=current_user,
        org_id=org_id,
        target_user_id=user_id,
    )
    return MessageResponse(message="Member removed from organization successfully.")
