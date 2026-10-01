"""Service API route handlers for tenant- and environment-scoped CRUD operations."""

from typing import Annotated
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db_session
from app.models.organization_member import OrganizationMember
from app.schemas.service import (
    CreateServiceRequest,
    ServiceResponse,
    UpdateServiceRequest,
)
from app.services.service_service import ServiceService

router = APIRouter(
    prefix="/api/v1/organizations/{org_id}/projects/{project_id}/environments/{environment_id}/services",
    tags=["Services"],
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceResponse,
    summary="Create a new service",
)
async def create_service(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    payload: CreateServiceRequest,
    member: Annotated[OrganizationMember, Depends(require_permission("service:create"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceResponse:
    """Create a new service workload within the specified environment (requires service:create)."""
    service = await ServiceService.create_service(
        db=db,
        org_id=org_id,
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
    )
    return ServiceResponse.model_validate(service)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=list[ServiceResponse],
    summary="List services in an environment",
)
async def list_services(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    member: Annotated[OrganizationMember, Depends(require_permission("service:read"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ServiceResponse]:
    """List all services belonging strictly to the specified environment (requires service:read)."""
    services = await ServiceService.list_services(
        db=db,
        org_id=org_id,
        project_id=project_id,
        environment_id=environment_id,
    )
    return [ServiceResponse.model_validate(s) for s in services]


@router.get(
    "/{service_id}",
    status_code=status.HTTP_200_OK,
    response_model=ServiceResponse,
    summary="Get service details",
)
async def get_service(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    service_id: uuid.UUID,
    member: Annotated[OrganizationMember, Depends(require_permission("service:read"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceResponse:
    """Retrieve details for a specific service within the environment (requires service:read).

    Returns 404 if the service does not exist, belongs to another environment, or belongs to another tenant.
    """
    service = await ServiceService.get_service(
        db=db,
        org_id=org_id,
        project_id=project_id,
        environment_id=environment_id,
        service_id=service_id,
    )
    return ServiceResponse.model_validate(service)


@router.patch(
    "/{service_id}",
    status_code=status.HTTP_200_OK,
    response_model=ServiceResponse,
    summary="Update service metadata",
)
async def update_service(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    service_id: uuid.UUID,
    payload: UpdateServiceRequest,
    member: Annotated[OrganizationMember, Depends(require_permission("service:update"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceResponse:
    """Update permitted metadata for an active service (requires service:update)."""
    service = await ServiceService.update_service(
        db=db,
        org_id=org_id,
        project_id=project_id,
        environment_id=environment_id,
        service_id=service_id,
        payload=payload,
    )
    return ServiceResponse.model_validate(service)


@router.delete(
    "/{service_id}",
    status_code=status.HTTP_200_OK,
    response_model=ServiceResponse,
    summary="Soft-delete (deactivate) a service",
)
async def delete_service(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
    service_id: uuid.UUID,
    member: Annotated[OrganizationMember, Depends(require_permission("service:delete"))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceResponse:
    """Safely soft-delete a service by setting is_active=False (requires service:delete)."""
    service = await ServiceService.delete_service(
        db=db,
        org_id=org_id,
        project_id=project_id,
        environment_id=environment_id,
        service_id=service_id,
    )
    return ServiceResponse.model_validate(service)
