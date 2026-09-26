"""Organization API route handlers for multi-tenant management."""

from typing import Annotated
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_verified_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.organization import (
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
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
