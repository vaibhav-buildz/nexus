"""Project domain service managing project lifecycle and tenant isolation."""

import logging
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    InactiveProjectError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
)
from app.models.project import Project
from app.schemas.project import CreateProjectRequest, UpdateProjectRequest

logger = logging.getLogger("nexus.project")


class ProjectService:
    """Core domain service for Project operations with strict tenant boundary enforcement."""

    @staticmethod
    async def create_project(
        db: AsyncSession,
        org_id: uuid.UUID,
        payload: CreateProjectRequest,
    ) -> Project:
        """Create a new project scoped to the organization.

        Enforces uniqueness of slug per organization and prevents client from controlling
        organization_id or is_active lifecycle flags.
        """
        existing = await db.scalar(
            select(Project).where(
                Project.organization_id == org_id,
                Project.slug == payload.slug,
            )
        )
        if existing:
            raise ProjectAlreadyExistsError(
                "A project with this slug already exists in this organization."
            )

        project = Project(
            organization_id=org_id,
            name=payload.name,
            slug=payload.slug,
            description=payload.description.strip() if payload.description else None,
            is_active=True,
        )
        db.add(project)

        try:
            await db.commit()
            await db.refresh(project)
            return project
        except IntegrityError as exc:
            await db.rollback()
            logger.warning("Duplicate slug conflict during project creation: %s", exc)
            raise ProjectAlreadyExistsError(
                "A project with this slug already exists in this organization."
            )
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def list_projects(
        db: AsyncSession,
        org_id: uuid.UUID,
    ) -> list[Project]:
        """List all projects belonging strictly to the specified organization.

        Ordered deterministically by created_at ascending, then id ascending.
        Never returns projects belonging to another tenant.
        """
        stmt = (
            select(Project)
            .where(Project.organization_id == org_id)
            .order_by(Project.created_at.asc(), Project.id.asc())
        )
        result = await db.scalars(stmt)
        return list(result.all())

    @staticmethod
    async def get_project(
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> Project:
        """Retrieve project with strict tenant scoping.

        If the project does not exist or belongs to another organization, raises
        ProjectNotFoundError (404) to avoid cross-tenant resource enumeration.
        """
        stmt = select(Project).where(
            Project.id == project_id,
            Project.organization_id == org_id,
        )
        project = await db.scalar(stmt)
        if not project:
            raise ProjectNotFoundError("Project not found.")
        return project

    @staticmethod
    async def update_project(
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        payload: UpdateProjectRequest,
    ) -> Project:
        """Update permitted metadata on an active project within the organization context."""
        stmt = select(Project).where(
            Project.id == project_id,
            Project.organization_id == org_id,
        )
        project = await db.scalar(stmt)
        if not project:
            raise ProjectNotFoundError("Project not found.")

        if not project.is_active:
            raise InactiveProjectError("Cannot update an inactive project.")

        # If slug is being updated, verify uniqueness within this organization
        if payload.slug is not None and payload.slug != project.slug:
            existing_slug = await db.scalar(
                select(Project).where(
                    Project.organization_id == org_id,
                    Project.slug == payload.slug,
                    Project.id != project_id,
                )
            )
            if existing_slug:
                raise ProjectAlreadyExistsError(
                    "A project with this slug already exists in this organization."
                )
            project.slug = payload.slug

        if payload.name is not None:
            project.name = payload.name

        if "description" in payload.model_fields_set:
            project.description = (
                payload.description.strip() if payload.description else None
            )

        try:
            await db.commit()
            await db.refresh(project)
            return project
        except IntegrityError as exc:
            await db.rollback()
            logger.warning("Integrity error during project update: %s", exc)
            raise ProjectAlreadyExistsError(
                "A project with this slug already exists in this organization."
            )
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def delete_project(
        db: AsyncSession,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> Project:
        """Soft-deactivate a project within the organization context.

        Sets is_active=False without deleting operational history.
        Safely idempotent if the project is already inactive.
        """
        stmt = select(Project).where(
            Project.id == project_id,
            Project.organization_id == org_id,
        )
        project = await db.scalar(stmt)
        if not project:
            raise ProjectNotFoundError("Project not found.")

        project.is_active = False
        await db.commit()
        await db.refresh(project)
        return project
