"""Environment API route handlers for tenant- and project-scoped CRUD operations."""

from typing import Annotated
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db_session
from app.models.organization_member import OrganizationMember
from app.schemas.environment import (
    CreateEnvironmentRequest,
    EnvironmentResponse,
    UpdateEnvironmentRequest,
)
from app.services.environment_service import EnvironmentService

router = APIRouter(
    prefix="/api/v1/organizations/{org_id}/projects/{project_id}/environments",
    tags=["Environments"],
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=EnvironmentResponse,
    summary="Create a new environment",
)
async def create_environment(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: CreateEnvironmentRequest,
    member: Annotated[OrganizationMember, Depends(require_permission("environment:create"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> EnvironmentResponse:
    """Create a new environment within the specified project and organization (requires environment:create)."""
    environment = await EnvironmentService.create_environment(
        db=db,
        org_id=org_id,
        project_id=project_id,
        payload=payload,
    )
    return EnvironmentResponse.model_validate(environment)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=list[EnvironmentResponse],
    summary="List environments in a project",
)
async def list_environments(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    member: Annotated[OrganizationMember, Depends(require_permission("environment:read"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[EnvironmentResponse]:
    """List all environments belonging strictly to the specified project (requires environment:read)."""
    environments = await EnvironmentService.list_environments(
        db=db,
        org_id=org_id,
        project_id=project_id,
    )
    return [EnvironmentResponse.model_validate(e) for e in environments]


@router.get(
    "/{environment_id}",
    status_code=status.HTTP_200_OK,
    response_model=EnvironmentResponse,
    summary="Get environment details",
)
async def get_environment(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    member: Annotated[OrganizationMember, Depends(require_permission("environment:read"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> EnvironmentResponse:
    """Retrieve details for a specific environment within the project (requires environment:read).

    Returns 404 if the environment does not exist, belongs to another project, or belongs to another tenant.
    """
    environment = await EnvironmentService.get_environment(
        db=db,
        org_id=org_id,
        project_id=project_id,
        environment_id=environment_id,
    )
    return EnvironmentResponse.model_validate(environment)


@router.patch(
    "/{environment_id}",
    status_code=status.HTTP_200_OK,
    response_model=EnvironmentResponse,
    summary="Update environment metadata",
)
async def update_environment(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    payload: UpdateEnvironmentRequest,
    member: Annotated[OrganizationMember, Depends(require_permission("environment:update"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> EnvironmentResponse:
    """Update permitted metadata for an active environment (requires environment:update)."""
    environment = await EnvironmentService.update_environment(
        db=db,
        org_id=org_id,
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
    )
    return EnvironmentResponse.model_validate(environment)


@router.delete(
    "/{environment_id}",
    status_code=status.HTTP_200_OK,
    response_model=EnvironmentResponse,
    summary="Soft-delete (deactivate) an environment",
)
async def delete_environment(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    member: Annotated[OrganizationMember, Depends(require_permission("environment:delete"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> EnvironmentResponse:
    """Safely soft-delete an environment by setting is_active=False (requires environment:delete)."""
    environment = await EnvironmentService.delete_environment(
        db=db,
        org_id=org_id,
        project_id=project_id,
        environment_id=environment_id,
    )
    return EnvironmentResponse.model_validate(environment)
