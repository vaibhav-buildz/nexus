"""Service domain service managing workload component lifecycle, hierarchy validation, and tenant isolation."""

import logging
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    EnvironmentNotFoundError,
    InactiveEnvironmentError,
    InactiveServiceError,
    ProjectNotFoundError,
    ServiceAlreadyExistsError,
    ServiceNotFoundError,
)
from app.models.environment import Environment
from app.models.project import Project
from app.models.service import Service, ServiceType
from app.schemas.service import CreateServiceRequest, UpdateServiceRequest

logger = logging.getLogger("nexus.service")


class ServiceService:
    """Core domain service for Service operations with strict 4-level hierarchy and tenant scoping."""

    @staticmethod
    async def _get_environment_in_project_and_org(
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        environment_id: uuid.UUID,
    ) -> Environment:
        """Verify and retrieve parent environment scoped strictly to the specified project and organization.

        Raises:
            ProjectNotFoundError (404): If project does not exist in the organization context.
            EnvironmentNotFoundError (404): If environment does not exist in the project and organization context.
        """
        project = await db.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == org_id,
            )
        )
        if not project:
            raise ProjectNotFoundError("Project not found.")

        environment = await db.scalar(
            select(Environment).where(
                Environment.id == environment_id,
                Environment.project_id == project_id,
                Environment.organization_id == org_id,
            )
        )
        if not environment:
            raise EnvironmentNotFoundError("Environment not found.")
        return environment

    @classmethod
    async def create_service(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        environment_id: uuid.UUID,
        payload: CreateServiceRequest,
    ) -> Service:
        """Create a new service within the specified environment, project, and organization.

        Enforces active environment requirement and slug uniqueness within the environment.
        """
        environment = await cls._get_environment_in_project_and_org(
            db=db,
            org_id=org_id,
            project_id=project_id,
            environment_id=environment_id,
        )

        if not environment.is_active:
            raise InactiveEnvironmentError("Cannot create a service in an inactive environment.")

        # Check slug uniqueness within environment
        existing = await db.scalar(
            select(Service).where(
                Service.environment_id == environment_id,
                Service.slug == payload.slug,
            )
        )
        if existing:
            raise ServiceAlreadyExistsError(
                "A service with this slug already exists in this environment."
            )

        str_service_type = (
            payload.service_type.value
            if isinstance(payload.service_type, ServiceType)
            else str(payload.service_type)
        )

        service = Service(
            organization_id=org_id,
            project_id=project_id,
            environment_id=environment_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description.strip() if payload.description else None,
            service_type=str_service_type,
            is_active=True,
        )
        db.add(service)

        try:
            await db.commit()
            await db.refresh(service)
            return service
        except IntegrityError as exc:
            await db.rollback()
            logger.warning("Duplicate slug conflict during service creation: %s", exc)
            raise ServiceAlreadyExistsError(
                "A service with this slug already exists in this environment."
            )
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def list_services(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        environment_id: uuid.UUID,
    ) -> list[Service]:
        """List all services belonging strictly to the specified environment, project, and organization.

        Deterministic ordering by created_at ascending, then id ascending.
        """
        await cls._get_environment_in_project_and_org(
            db=db,
            org_id=org_id,
            project_id=project_id,
            environment_id=environment_id,
        )

        stmt = (
            select(Service)
            .where(
                Service.organization_id == org_id,
                Service.project_id == project_id,
                Service.environment_id == environment_id,
            )
            .order_by(Service.created_at.asc(), Service.id.asc())
        )
        result = await db.scalars(stmt)
        return list(result.all())

    @classmethod
    async def get_service(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        environment_id: uuid.UUID,
        service_id: uuid.UUID,
    ) -> Service:
        """Retrieve service with strict 4-level hierarchy and tenant scoping."""
        await cls._get_environment_in_project_and_org(
            db=db,
            org_id=org_id,
            project_id=project_id,
            environment_id=environment_id,
        )

        stmt = select(Service).where(
            Service.id == service_id,
            Service.environment_id == environment_id,
            Service.project_id == project_id,
            Service.organization_id == org_id,
        )
        service = await db.scalar(stmt)
        if not service:
            raise ServiceNotFoundError("Service not found.")
        return service

    @classmethod
    async def update_service(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        environment_id: uuid.UUID,
        service_id: uuid.UUID,
        payload: UpdateServiceRequest,
    ) -> Service:
        """Update permitted metadata on an active service within the environment context."""
        await cls._get_environment_in_project_and_org(
            db=db,
            org_id=org_id,
            project_id=project_id,
            environment_id=environment_id,
        )

        stmt = select(Service).where(
            Service.id == service_id,
            Service.environment_id == environment_id,
            Service.project_id == project_id,
            Service.organization_id == org_id,
        )
        service = await db.scalar(stmt)
        if not service:
            raise ServiceNotFoundError("Service not found.")

        if not service.is_active:
            raise InactiveServiceError("Cannot update an inactive service.")

        # If slug is being updated, verify uniqueness within this environment
        if payload.slug is not None and payload.slug != service.slug:
            existing_slug = await db.scalar(
                select(Service).where(
                    Service.environment_id == environment_id,
                    Service.slug == payload.slug,
                    Service.id != service_id,
                )
            )
            if existing_slug:
                raise ServiceAlreadyExistsError(
                    "A service with this slug already exists in this environment."
                )
            service.slug = payload.slug

        if payload.name is not None:
            service.name = payload.name

        if "description" in payload.model_fields_set:
            service.description = (
                payload.description.strip() if payload.description else None
            )

        if payload.service_type is not None:
            service.service_type = (
                payload.service_type.value
                if isinstance(payload.service_type, ServiceType)
                else str(payload.service_type)
            )

        try:
            await db.commit()
            await db.refresh(service)
            return service
        except IntegrityError as exc:
            await db.rollback()
            logger.warning("Integrity error during service update: %s", exc)
            raise ServiceAlreadyExistsError(
                "A service with this slug already exists in this environment."
            )
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def delete_service(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        environment_id: uuid.UUID,
        service_id: uuid.UUID,
    ) -> Service:
        """Soft-deactivate a service within the environment, project, and organization context.

        Sets is_active=False without deleting operational history.
        Safely idempotent if the service is already inactive.
        """
        await cls._get_environment_in_project_and_org(
            db=db,
            org_id=org_id,
            project_id=project_id,
            environment_id=environment_id,
        )

        stmt = select(Service).where(
            Service.id == service_id,
            Service.environment_id == environment_id,
            Service.project_id == project_id,
            Service.organization_id == org_id,
        )
        service = await db.scalar(stmt)
        if not service:
            raise ServiceNotFoundError("Service not found.")

        service.is_active = False
        await db.commit()
        await db.refresh(service)
        return service
