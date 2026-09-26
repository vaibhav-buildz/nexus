"""Organization service managing multi-tenant lifecycle, transactions, and isolation."""

import logging
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import (
    InactiveOrganizationError,
    InsufficientPermissionsError,
    OrganizationAlreadyExistsError,
    OrganizationNotFoundError,
)
from app.core.rbac import OrgRole, Permission, has_permission
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.schemas.organization import OrganizationCreateRequest, OrganizationUpdateRequest

logger = logging.getLogger("nexus.organization")


class OrganizationService:
    """Core domain service for organization management and multi-tenant isolation."""

    @staticmethod
    async def create_organization(
        db: AsyncSession,
        creator: User,
        payload: OrganizationCreateRequest,
    ) -> Organization:
        """Create a new organization and assign creator as OWNER in a single atomic transaction.

        If either operation fails, transaction rolls back so neither persists.
        """
        normalized_slug = payload.slug.strip().lower()

        # Check existing slug to catch early
        existing = await db.scalar(select(Organization).where(Organization.slug == normalized_slug))
        if existing:
            raise OrganizationAlreadyExistsError("An organization with this slug already exists.")

        try:
            # 1. Create Organization entity
            new_org = Organization(
                name=payload.name.strip(),
                slug=normalized_slug,
                description=payload.description.strip() if payload.description else None,
                is_active=True,
            )
            db.add(new_org)
            await db.flush()

            # 2. Create OrganizationMember entity linking creator as OWNER
            owner_member = OrganizationMember(
                organization_id=new_org.id,
                user_id=creator.id,
                role=OrgRole.OWNER.value,
            )
            db.add(owner_member)
            await db.flush()

            # 3. Commit atomically
            await db.commit()
            await db.refresh(new_org)
            return new_org

        except IntegrityError as exc:
            await db.rollback()
            logger.warning("Duplicate slug conflict during organization creation: %s", exc)
            raise OrganizationAlreadyExistsError("An organization with this slug already exists.")
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def list_user_organizations(
        db: AsyncSession,
        user: User,
    ) -> list[Organization]:
        """Return only organizations where the current user has an active membership row.

        Never returns organizations belonging to other users.
        """
        stmt = (
            select(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user.id)
            .order_by(Organization.created_at.desc())
        )
        result = await db.scalars(stmt)
        return list(result.all())

    @staticmethod
    async def get_organization_for_user(
        db: AsyncSession,
        user: User,
        org_id: uuid.UUID,
    ) -> Organization:
        """Retrieve organization details for an authenticated member.

        Prevents tenant existence enumeration: non-members receive 404 Not Found.
        """
        # Verify membership first to prevent tenant enumeration
        membership = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user.id,
            )
        )
        if not membership:
            raise OrganizationNotFoundError("Organization not found.")

        org = await db.scalar(select(Organization).where(Organization.id == org_id))
        if not org:
            raise OrganizationNotFoundError("Organization not found.")

        if not org.is_active:
            raise InactiveOrganizationError("Organization is inactive.")

        if not has_permission(membership.role, Permission.ORG_READ):
            raise InsufficientPermissionsError("Insufficient permissions.")

        return org

    @staticmethod
    async def update_organization(
        db: AsyncSession,
        user: User,
        org_id: uuid.UUID,
        payload: OrganizationUpdateRequest,
    ) -> Organization:
        """Update permitted organization metadata fields (requires org:update permission)."""
        membership = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user.id,
            )
        )
        if not membership:
            raise OrganizationNotFoundError("Organization not found.")

        org = await db.scalar(select(Organization).where(Organization.id == org_id))
        if not org:
            raise OrganizationNotFoundError("Organization not found.")

        if not org.is_active:
            raise InactiveOrganizationError("Organization is inactive.")

        if not has_permission(membership.role, Permission.ORG_UPDATE):
            raise InsufficientPermissionsError("Insufficient permissions.")

        # Update only permitted fields
        if payload.name is not None:
            org.name = payload.name.strip()
        if payload.description is not None:
            org.description = payload.description.strip() if payload.description else None

        await db.commit()
        await db.refresh(org)
        return org

    @staticmethod
    async def deactivate_organization(
        db: AsyncSession,
        user: User,
        org_id: uuid.UUID,
    ) -> Organization:
        """Safely deactivate an organization by setting is_active to False.

        Requires org:delete permission (restricted to OWNER only).
        Destructive permanent cascading deletion is intentionally omitted for Phase 2.
        """
        membership = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user.id,
            )
        )
        if not membership:
            raise OrganizationNotFoundError("Organization not found.")

        org = await db.scalar(select(Organization).where(Organization.id == org_id))
        if not org:
            raise OrganizationNotFoundError("Organization not found.")

        if not has_permission(membership.role, Permission.ORG_DELETE):
            raise InsufficientPermissionsError("Insufficient permissions.")

        org.is_active = False
        await db.commit()
        await db.refresh(org)
        return org
