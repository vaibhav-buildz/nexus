"""Membership domain service managing organization members, role changes, and RBAC governance."""

import logging
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import (
    GovernanceRuleViolationError,
    InactiveOrganizationError,
    InactiveUserError,
    InsufficientPermissionsError,
    MemberAlreadyExistsError,
    MemberNotFoundError,
    OrganizationNotFoundError,
    UserNotFoundError,
)
from app.core.rbac import (
    OrgRole,
    Permission,
    has_permission,
    validate_member_removal,
    validate_role_assignment,
)
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.schemas.member import MemberAddRequest, MemberResponse

logger = logging.getLogger("nexus.membership")


class MembershipService:
    """Core domain service for membership management and governance enforcement."""

    @staticmethod
    async def list_members(
        db: AsyncSession,
        current_user: User,
        org_id: uuid.UUID,
    ) -> list[MemberResponse]:
        """Return all members belonging strictly to the requested organization context."""
        # 1. Verify caller membership to prevent tenant enumeration
        caller_membership = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == current_user.id,
            )
        )
        if not caller_membership:
            raise OrganizationNotFoundError("Organization not found.")

        # 2. Verify active organization
        org = await db.scalar(select(Organization).where(Organization.id == org_id))
        if not org:
            raise OrganizationNotFoundError("Organization not found.")
        if not org.is_active:
            raise InactiveOrganizationError("Organization is inactive.")

        # 3. Check permission
        if not has_permission(caller_membership.role, Permission.MEMBER_READ):
            raise InsufficientPermissionsError("Insufficient permissions.")

        # 4. Fetch members scoped strictly to this organization
        stmt = (
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user))
            .where(OrganizationMember.organization_id == org_id)
            .order_by(OrganizationMember.created_at.asc())
        )
        members = (await db.scalars(stmt)).all()

        return [
            MemberResponse(
                id=m.id,
                organization_id=m.organization_id,
                user_id=m.user_id,
                role=m.role,
                email=m.user.email if m.user else None,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
            for m in members
        ]

    @staticmethod
    async def add_member(
        db: AsyncSession,
        current_user: User,
        org_id: uuid.UUID,
        payload: MemberAddRequest,
    ) -> MemberResponse:
        """Add an existing registered user to the organization with assigned role."""
        # 1. Verify caller membership & permission
        caller_membership = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == current_user.id,
            )
        )
        if not caller_membership:
            raise OrganizationNotFoundError("Organization not found.")

        # 2. Verify organization is active
        org = await db.scalar(select(Organization).where(Organization.id == org_id))
        if not org:
            raise OrganizationNotFoundError("Organization not found.")
        if not org.is_active:
            raise InactiveOrganizationError("Organization is inactive.")

        # 3. Check caller permission to invite members
        if not has_permission(caller_membership.role, Permission.MEMBER_INVITE):
            raise InsufficientPermissionsError("Insufficient permissions.")

        # 4. Find target user by user_id or email (or both)
        target_user = None
        if payload.user_id and payload.email:
            target_user = await db.scalar(
                select(User).where(
                    User.id == payload.user_id,
                    User.email == payload.email.lower().strip(),
                )
            )
        elif payload.user_id:
            target_user = await db.scalar(select(User).where(User.id == payload.user_id))
        elif payload.email:
            target_user = await db.scalar(
                select(User).where(User.email == payload.email.lower().strip())
            )

        if not target_user:
            raise UserNotFoundError("User not found.")

        if not target_user.is_active:
            raise InactiveUserError("User account is inactive.")

        # 5. Check for duplicate membership
        existing_membership = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == target_user.id,
            )
        )
        if existing_membership:
            raise MemberAlreadyExistsError("User is already a member of this organization.")

        # 5. Governance validation: ADMIN cannot assign OWNER or above ADMIN; OWNER may assign OWNER
        validate_role_assignment(
            actor_id=current_user.id,
            actor_role=caller_membership.role,
            target_id=target_user.id,
            target_current_role=None,
            target_new_role=payload.role,
        )

        try:
            new_member = OrganizationMember(
                organization_id=org_id,
                user_id=target_user.id,
                role=payload.role.value,
            )
            db.add(new_member)
            await db.commit()
            await db.refresh(new_member)

            return MemberResponse(
                id=new_member.id,
                organization_id=new_member.organization_id,
                user_id=new_member.user_id,
                role=new_member.role,
                email=target_user.email,
                created_at=new_member.created_at,
                updated_at=new_member.updated_at,
            )
        except IntegrityError:
            await db.rollback()
            raise MemberAlreadyExistsError("User is already a member of this organization.")
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def update_member_role(
        db: AsyncSession,
        current_user: User,
        org_id: uuid.UUID,
        target_user_id: uuid.UUID,
        new_role: OrgRole,
    ) -> MemberResponse:
        """Update a member's role enforcing all RBAC and last-owner governance rules."""
        # 1. Verify caller membership & permission
        caller_membership = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == current_user.id,
            )
        )
        if not caller_membership:
            raise OrganizationNotFoundError("Organization not found.")

        # 2. Verify organization is active
        org = await db.scalar(select(Organization).where(Organization.id == org_id))
        if not org:
            raise OrganizationNotFoundError("Organization not found.")
        if not org.is_active:
            raise InactiveOrganizationError("Organization is inactive.")

        # 3. Find target member strictly within this organization
        target_member = await db.scalar(
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user))
            .where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == target_user_id,
            )
        )
        if not target_member:
            raise MemberNotFoundError("Member not found in this organization.")

        # 4. Count current owners to protect against demoting the last owner
        owners_query = select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.role == OrgRole.OWNER.value,
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            owners_query = owners_query.with_for_update()

        owners = (await db.scalars(owners_query)).all()
        owner_count = len(owners)

        # 5. Governance validation
        validate_role_assignment(
            actor_id=current_user.id,
            actor_role=caller_membership.role,
            target_id=target_user_id,
            target_current_role=target_member.role,
            target_new_role=new_role,
            current_owner_count=owner_count,
        )

        target_member.role = new_role.value
        await db.commit()
        await db.refresh(target_member)

        return MemberResponse(
            id=target_member.id,
            organization_id=target_member.organization_id,
            user_id=target_member.user_id,
            role=target_member.role,
            email=target_member.user.email if target_member.user else None,
            created_at=target_member.created_at,
            updated_at=target_member.updated_at,
        )

    @staticmethod
    async def remove_member(
        db: AsyncSession,
        current_user: User,
        org_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> None:
        """Remove a member or self-leave from an organization, strictly enforcing last-owner rules."""
        # 1. Verify caller membership & permission
        caller_membership = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == current_user.id,
            )
        )
        if not caller_membership:
            raise OrganizationNotFoundError("Organization not found.")

        # 2. Verify organization is active
        org = await db.scalar(select(Organization).where(Organization.id == org_id))
        if not org:
            raise OrganizationNotFoundError("Organization not found.")
        if not org.is_active:
            raise InactiveOrganizationError("Organization is inactive.")

        # 3. Find target member strictly within this organization
        target_member = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == target_user_id,
            )
        )
        if not target_member:
            raise MemberNotFoundError("Member not found in this organization.")

        # 4. Count current owners to protect against removing the last owner
        owners_query = select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.role == OrgRole.OWNER.value,
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            owners_query = owners_query.with_for_update()

        owners = (await db.scalars(owners_query)).all()
        owner_count = len(owners)

        # 5. Governance validation: ADMIN cannot remove OWNER; sole OWNER cannot leave/be removed
        validate_member_removal(
            actor_id=current_user.id,
            actor_role=caller_membership.role,
            target_id=target_user_id,
            target_role=target_member.role,
            current_owner_count=owner_count,
        )

        # 6. Delete membership in transaction
        await db.delete(target_member)
        await db.commit()
