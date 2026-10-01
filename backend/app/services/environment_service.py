"""Environment domain service managing environment lifecycle, parent hierarchy, and tenant isolation."""

import logging
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    EnvironmentAlreadyExistsError,
    EnvironmentNotFoundError,
    InactiveEnvironmentError,
    InactiveProjectError,
    ProjectNotFoundError,
)
from app.models.environment import Environment
from app.models.project import Project
from app.schemas.environment import CreateEnvironmentRequest, UpdateEnvironmentRequest

logger = logging.getLogger("nexus.environment")


class EnvironmentService:
    """Core domain service for Environment operations with strict parent hierarchy and tenant enforcement."""

    @staticmethod
    async def _get_project_in_org(
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> Project:
        """Verify and retrieve parent project scoped to the specified organization.

        Raises ProjectNotFoundError (404) if the project does not exist or belongs
        to a different organization.
        """
        stmt = select(Project).where(
            Project.id == project_id,
            Project.organization_id == org_id,
        )
        project = await db.scalar(stmt)
        if not project:
            raise ProjectNotFoundError("Project not found.")
        return project

    @classmethod
    async def create_environment(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        payload: CreateEnvironmentRequest,
    ) -> Environment:
        """Create a new environment within the specified project and organization.

        Validates parent project active status and uniqueness of slug within the project.
        """
        project = await cls._get_project_in_org(db=db, org_id=org_id, project_id=project_id)
        if not project.is_active:
            raise InactiveProjectError("Cannot create an environment in an inactive project.")

        # Check slug uniqueness within project
        existing = await db.scalar(
            select(Environment).where(
                Environment.project_id == project_id,
                Environment.slug == payload.slug,
            )
        )
        if existing:
            raise EnvironmentAlreadyExistsError(
                "An environment with this slug already exists in this project."
            )

        environment = Environment(
            organization_id=org_id,
            project_id=project_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description.strip() if payload.description else None,
            is_active=True,
        )
        db.add(environment)

        try:
            await db.commit()
            await db.refresh(environment)
            return environment
        except IntegrityError as exc:
            await db.rollback()
            logger.warning("Duplicate slug conflict during environment creation: %s", exc)
            raise EnvironmentAlreadyExistsError(
                "An environment with this slug already exists in this project."
            )
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def list_environments(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> list[Environment]:
        """List all environments belonging strictly to the specified project and organization.

        Deterministic ordering by created_at ascending, then id ascending.
        """
        await cls._get_project_in_org(db=db, org_id=org_id, project_id=project_id)

        stmt = (
            select(Environment)
            .where(
                Environment.project_id == project_id,
                Environment.organization_id == org_id,
            )
            .order_by(Environment.created_at.asc(), Environment.id.asc())
        )
        result = await db.scalars(stmt)
        return list(result.all())

    @classmethod
    async def get_environment(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        environment_id: uuid.UUID,
    ) -> Environment:
        """Retrieve environment with strict parent hierarchy and tenant scoping."""
        await cls._get_project_in_org(db=db, org_id=org_id, project_id=project_id)

        stmt = select(Environment).where(
            Environment.id == environment_id,
            Environment.project_id == project_id,
            Environment.organization_id == org_id,
        )
        environment = await db.scalar(stmt)
        if not environment:
            raise EnvironmentNotFoundError("Environment not found.")
        return environment

    @classmethod
    async def update_environment(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        environment_id: uuid.UUID,
        payload: UpdateEnvironmentRequest,
    ) -> Environment:
        """Update permitted metadata on an active environment within the parent project."""
        await cls._get_project_in_org(db=db, org_id=org_id, project_id=project_id)

        stmt = select(Environment).where(
            Environment.id == environment_id,
            Environment.project_id == project_id,
            Environment.organization_id == org_id,
        )
        environment = await db.scalar(stmt)
        if not environment:
            raise EnvironmentNotFoundError("Environment not found.")

        if not environment.is_active:
            raise InactiveEnvironmentError("Cannot update an inactive environment.")

        # If slug is being updated, verify uniqueness within this project
        if payload.slug is not None and payload.slug != environment.slug:
            existing_slug = await db.scalar(
                select(Environment).where(
                    Environment.project_id == project_id,
                    Environment.slug == payload.slug,
                    Environment.id != environment_id,
                )
            )
            if existing_slug:
                raise EnvironmentAlreadyExistsError(
                    "An environment with this slug already exists in this project."
                )
            environment.slug = payload.slug

        if payload.name is not None:
            environment.name = payload.name

        if "description" in payload.model_fields_set:
            environment.description = (
                payload.description.strip() if payload.description else None
            )

        try:
            await db.commit()
            await db.refresh(environment)
            return environment
        except IntegrityError as exc:
            await db.rollback()
            logger.warning("Integrity error during environment update: %s", exc)
            raise EnvironmentAlreadyExistsError(
                "An environment with this slug already exists in this project."
            )
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def delete_environment(
        cls,
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        environment_id: uuid.UUID,
    ) -> Environment:
        """Soft-deactivate an environment within the project and organization context.

        Sets is_active=False without deleting operational history.
        Safely idempotent if the environment is already inactive.
        """
        await cls._get_project_in_org(db=db, org_id=org_id, project_id=project_id)

        stmt = select(Environment).where(
            Environment.id == environment_id,
            Environment.project_id == project_id,
            Environment.organization_id == org_id,
        )
        environment = await db.scalar(stmt)
        if not environment:
            raise EnvironmentNotFoundError("Environment not found.")

        environment.is_active = False
        await db.commit()
        await db.refresh(environment)
        return environment
