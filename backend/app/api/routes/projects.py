"""Project API route handlers for tenant-scoped CRUD operations."""

from typing import Annotated
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db_session
from app.models.organization_member import OrganizationMember
from app.schemas.project import (
    CreateProjectRequest,
    ProjectResponse,
    UpdateProjectRequest,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/v1/organizations/{org_id}/projects", tags=["Projects"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectResponse,
    summary="Create a new project",
)
async def create_project(
    org_id: uuid.UUID,
    payload: CreateProjectRequest,
    member: Annotated[OrganizationMember, Depends(require_permission("project:create"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProjectResponse:
    """Create a new project within the authenticated organization context (requires project:create)."""
    project = await ProjectService.create_project(
        db=db,
        org_id=org_id,
        payload=payload,
    )
    return ProjectResponse.model_validate(project)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=list[ProjectResponse],
    summary="List projects in an organization",
)
async def list_projects(
    org_id: uuid.UUID,
    member: Annotated[OrganizationMember, Depends(require_permission("project:read"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ProjectResponse]:
    """List all projects belonging to the target organization (requires project:read)."""
    projects = await ProjectService.list_projects(
        db=db,
        org_id=org_id,
    )
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get(
    "/{project_id}",
    status_code=status.HTTP_200_OK,
    response_model=ProjectResponse,
    summary="Get project details",
)
async def get_project(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    member: Annotated[OrganizationMember, Depends(require_permission("project:read"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProjectResponse:
    """Retrieve details for a specific project within the organization (requires project:read).

    Returns 404 if the project does not exist or belongs to another tenant.
    """
    project = await ProjectService.get_project(
        db=db,
        org_id=org_id,
        project_id=project_id,
    )
    return ProjectResponse.model_validate(project)


@router.patch(
    "/{project_id}",
    status_code=status.HTTP_200_OK,
    response_model=ProjectResponse,
    summary="Update project metadata",
)
async def update_project(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: UpdateProjectRequest,
    member: Annotated[OrganizationMember, Depends(require_permission("project:update"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProjectResponse:
    """Update permitted metadata for an active project (requires project:update)."""
    project = await ProjectService.update_project(
        db=db,
        org_id=org_id,
        project_id=project_id,
        payload=payload,
    )
    return ProjectResponse.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_200_OK,
    response_model=ProjectResponse,
    summary="Soft-delete (deactivate) a project",
)
async def delete_project(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    member: Annotated[OrganizationMember, Depends(require_permission("project:delete"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProjectResponse:
    """Safely soft-delete a project by setting is_active=False (requires project:delete)."""
    project = await ProjectService.delete_project(
        db=db,
        org_id=org_id,
        project_id=project_id,
    )
    return ProjectResponse.model_validate(project)
