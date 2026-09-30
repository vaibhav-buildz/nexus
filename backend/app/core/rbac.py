"""Role-Based Access Control (RBAC) and Governance engine for NEXUS."""

from enum import Enum
import logging
import uuid
from app.core.errors import (
    GovernanceRuleViolationError,
    InsufficientPermissionsError,
)

logger = logging.getLogger("nexus.rbac")


class OrgRole(str, Enum):
    """Controlled application-level organization membership roles."""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class Permission(str, Enum):
    """Fine-grained organization and resource permissions."""

    # Organization
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"

    # Membership
    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_ROLE_UPDATE = "member:role_update"
    MEMBER_REMOVE = "member:remove"

    # Future resources
    RESOURCE_READ = "resource:read"
    RESOURCE_CREATE = "resource:create"
    RESOURCE_UPDATE = "resource:update"
    RESOURCE_DELETE = "resource:delete"

    # Projects
    PROJECT_READ = "project:read"
    PROJECT_CREATE = "project:create"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"

    # Environments
    ENVIRONMENT_READ = "environment:read"
    ENVIRONMENT_CREATE = "environment:create"
    ENVIRONMENT_UPDATE = "environment:update"
    ENVIRONMENT_DELETE = "environment:delete"

    # Services
    SERVICE_READ = "service:read"
    SERVICE_CREATE = "service:create"
    SERVICE_UPDATE = "service:update"
    SERVICE_DELETE = "service:delete"


# Explicit Role to Permission mapping
ROLE_PERMISSIONS: dict[OrgRole, set[Permission]] = {
    OrgRole.VIEWER: {
        Permission.ORG_READ,
        Permission.MEMBER_READ,
        Permission.RESOURCE_READ,
        Permission.PROJECT_READ,
        Permission.ENVIRONMENT_READ,
        Permission.SERVICE_READ,
    },
    OrgRole.MEMBER: {
        Permission.ORG_READ,
        Permission.MEMBER_READ,
        Permission.RESOURCE_READ,
        Permission.RESOURCE_CREATE,
        Permission.RESOURCE_UPDATE,
        Permission.PROJECT_READ,
        Permission.PROJECT_CREATE,
        Permission.PROJECT_UPDATE,
        Permission.ENVIRONMENT_READ,
        Permission.ENVIRONMENT_CREATE,
        Permission.ENVIRONMENT_UPDATE,
        Permission.SERVICE_READ,
        Permission.SERVICE_CREATE,
        Permission.SERVICE_UPDATE,
    },
    OrgRole.ADMIN: {
        Permission.ORG_READ,
        Permission.MEMBER_READ,
        Permission.RESOURCE_READ,
        Permission.RESOURCE_CREATE,
        Permission.RESOURCE_UPDATE,
        Permission.ORG_UPDATE,
        Permission.MEMBER_INVITE,
        Permission.MEMBER_ROLE_UPDATE,
        Permission.MEMBER_REMOVE,
        Permission.RESOURCE_DELETE,
        Permission.PROJECT_READ,
        Permission.PROJECT_CREATE,
        Permission.PROJECT_UPDATE,
        Permission.PROJECT_DELETE,
        Permission.ENVIRONMENT_READ,
        Permission.ENVIRONMENT_CREATE,
        Permission.ENVIRONMENT_UPDATE,
        Permission.ENVIRONMENT_DELETE,
        Permission.SERVICE_READ,
        Permission.SERVICE_CREATE,
        Permission.SERVICE_UPDATE,
        Permission.SERVICE_DELETE,
    },
    OrgRole.OWNER: {
        Permission.ORG_READ,
        Permission.MEMBER_READ,
        Permission.RESOURCE_READ,
        Permission.RESOURCE_CREATE,
        Permission.RESOURCE_UPDATE,
        Permission.ORG_UPDATE,
        Permission.MEMBER_INVITE,
        Permission.MEMBER_ROLE_UPDATE,
        Permission.MEMBER_REMOVE,
        Permission.RESOURCE_DELETE,
        Permission.ORG_DELETE,
        Permission.PROJECT_READ,
        Permission.PROJECT_CREATE,
        Permission.PROJECT_UPDATE,
        Permission.PROJECT_DELETE,
        Permission.ENVIRONMENT_READ,
        Permission.ENVIRONMENT_CREATE,
        Permission.ENVIRONMENT_UPDATE,
        Permission.ENVIRONMENT_DELETE,
        Permission.SERVICE_READ,
        Permission.SERVICE_CREATE,
        Permission.SERVICE_UPDATE,
        Permission.SERVICE_DELETE,
    },
}


def has_permission(role: OrgRole | str, permission: Permission | str) -> bool:
    """Check if the given role has the requested permission.

    Authorization evaluates explicit permission sets, avoiding brittle numeric comparisons.
    """
    try:
        org_role = OrgRole(role) if isinstance(role, str) else role
        perm = Permission(permission) if isinstance(permission, str) else permission
    except ValueError:
        return False

    allowed_permissions = ROLE_PERMISSIONS.get(org_role, set())
    return perm in allowed_permissions


def can_promote_to_owner(actor_role: OrgRole | str) -> bool:
    """Check if actor has authority to promote a member to OWNER.

    Governance Rule: Only an OWNER can promote another member to OWNER.
    """
    try:
        return OrgRole(actor_role) == OrgRole.OWNER
    except ValueError:
        return False


def can_demote_owner(actor_role: OrgRole | str, current_owner_count: int = 2) -> bool:
    """Check if actor has authority to demote an OWNER.

    Governance Rules:
    - Only OWNER can demote an OWNER.
    - Prevent the last OWNER from being demoted.
    """
    try:
        if OrgRole(actor_role) != OrgRole.OWNER:
            return False
    except ValueError:
        return False
    return current_owner_count > 1


def can_modify_owner_role(actor_role: OrgRole | str) -> bool:
    """Check if actor can modify an OWNER's role.

    Governance Rule: ADMIN cannot modify another OWNER's role.
    """
    try:
        return OrgRole(actor_role) == OrgRole.OWNER
    except ValueError:
        return False


def can_remove_owner(actor_role: OrgRole | str, current_owner_count: int = 2) -> bool:
    """Check if actor can remove an OWNER from the organization.

    Governance Rules:
    - ADMIN cannot remove an OWNER.
    - Only OWNER can remove another OWNER.
    - Prevent the last OWNER from being removed.
    """
    try:
        if OrgRole(actor_role) != OrgRole.OWNER:
            return False
    except ValueError:
        return False
    return current_owner_count > 1


def is_last_owner(role: OrgRole | str, current_owner_count: int) -> bool:
    """Check if the role belongs to the last OWNER of the organization."""
    try:
        return OrgRole(role) == OrgRole.OWNER and current_owner_count <= 1
    except ValueError:
        return False


def is_self_escalation(
    actor_id: uuid.UUID | str,
    target_id: uuid.UUID | str,
    actor_role: OrgRole | str,
    target_new_role: OrgRole | str,
) -> bool:
    """Check if an operation attempts self privilege escalation.

    Governance Rule: A user cannot escalate their own privileges.
    """
    if str(actor_id) != str(target_id):
        return False

    try:
        actor_role_enum = OrgRole(actor_role)
        new_role_enum = OrgRole(target_new_role)
    except ValueError:
        return True

    actor_perms = ROLE_PERMISSIONS.get(actor_role_enum, set())
    new_perms = ROLE_PERMISSIONS.get(new_role_enum, set())

    # Escalation occurs if new role grants any permissions actor does not currently have
    if not new_perms.issubset(actor_perms):
        return True

    # Disallow modifying own role to any different role
    return actor_role_enum != new_role_enum


def validate_organization_membership(
    membership_org_id: uuid.UUID | str,
    context_org_id: uuid.UUID | str,
) -> bool:
    """Validate that membership strictly belongs to the target organization context."""
    return str(membership_org_id) == str(context_org_id)


def validate_role_assignment(
    actor_id: uuid.UUID | str,
    actor_role: OrgRole | str,
    target_id: uuid.UUID | str,
    target_current_role: OrgRole | str | None,
    target_new_role: OrgRole | str,
    current_owner_count: int = 1,
) -> None:
    """Enforce explicit governance rules when creating or updating a member's role.

    Raises:
        GovernanceRuleViolationError: When governance constraints are breached.
        InsufficientPermissionsError: When actor lacks base permissions.
    """
    try:
        actor_role_enum = OrgRole(actor_role)
        target_new_role_enum = OrgRole(target_new_role)
        target_current_enum = OrgRole(target_current_role) if target_current_role else None
    except ValueError:
        logger.warning("Invalid role specified in role assignment.")
        raise GovernanceRuleViolationError("Invalid role specified.")

    # 1. Self privilege escalation check
    if str(actor_id) == str(target_id):
        if is_self_escalation(actor_id, target_id, actor_role_enum, target_new_role_enum):
            logger.warning("User %s attempted self privilege escalation", actor_id)
            raise GovernanceRuleViolationError("Insufficient permissions.")

    # 2. Base permission check for managing roles/inviting
    required_perm = (
        Permission.MEMBER_ROLE_UPDATE if target_current_enum else Permission.MEMBER_INVITE
    )
    if not has_permission(actor_role_enum, required_perm):
        logger.warning("User %s lacking permission %s for role assignment", actor_id, required_perm)
        raise InsufficientPermissionsError("Insufficient permissions.")

    # 3. ADMIN cannot create/promote an OWNER
    if actor_role_enum == OrgRole.ADMIN and target_new_role_enum == OrgRole.OWNER:
        logger.warning("Admin %s attempted to promote/create OWNER %s", actor_id, target_id)
        raise GovernanceRuleViolationError("Insufficient permissions.")

    # 4. Only OWNER can promote another member to OWNER
    if target_new_role_enum == OrgRole.OWNER and not can_promote_to_owner(actor_role_enum):
        logger.warning("Non-owner %s attempted to promote member to OWNER", actor_id)
        raise GovernanceRuleViolationError("Insufficient permissions.")

    # 5. ADMIN cannot modify another OWNER's role
    if actor_role_enum == OrgRole.ADMIN and target_current_enum == OrgRole.OWNER:
        logger.warning("Admin %s attempted to modify OWNER %s role", actor_id, target_id)
        raise GovernanceRuleViolationError("Insufficient permissions.")

    # 6. Only OWNER can demote an OWNER
    if target_current_enum == OrgRole.OWNER and target_new_role_enum != OrgRole.OWNER:
        if not can_modify_owner_role(actor_role_enum):
            logger.warning("Non-owner %s attempted to demote OWNER %s", actor_id, target_id)
            raise GovernanceRuleViolationError("Insufficient permissions.")
        # 7. Prevent the last OWNER from being demoted
        if current_owner_count <= 1:
            logger.warning("Attempted to demote the last OWNER %s", target_id)
            raise GovernanceRuleViolationError("Cannot demote the last owner of the organization.")


def validate_member_removal(
    actor_id: uuid.UUID | str,
    actor_role: OrgRole | str,
    target_id: uuid.UUID | str,
    target_role: OrgRole | str,
    current_owner_count: int = 1,
) -> None:
    """Enforce explicit governance rules when removing a member or leaving an organization.

    Raises:
        GovernanceRuleViolationError: When governance constraints are breached.
        InsufficientPermissionsError: When actor lacks base permissions.
    """
    try:
        actor_role_enum = OrgRole(actor_role)
        target_role_enum = OrgRole(target_role)
    except ValueError:
        logger.warning("Invalid role specified in member removal.")
        raise GovernanceRuleViolationError("Invalid role specified.")

    is_self = str(actor_id) == str(target_id)

    # 1. Prevent the last OWNER from leaving or being removed
    if target_role_enum == OrgRole.OWNER and current_owner_count <= 1:
        logger.warning(
            "Prevented removing or leaving as the last OWNER (target: %s, actor: %s)",
            target_id,
            actor_id,
        )
        raise GovernanceRuleViolationError(
            "Cannot remove or leave as the last owner of an organization."
        )

    # 2. Self removal (leaving organization)
    if is_self:
        return

    # 3. Base permission check for removing other members
    if not has_permission(actor_role_enum, Permission.MEMBER_REMOVE):
        logger.warning("User %s lacking member:remove permission", actor_id)
        raise InsufficientPermissionsError("Insufficient permissions.")

    # 4. ADMIN cannot demote/remove an OWNER
    if actor_role_enum == OrgRole.ADMIN and target_role_enum == OrgRole.OWNER:
        logger.warning("Admin %s attempted to remove OWNER %s", actor_id, target_id)
        raise GovernanceRuleViolationError("Insufficient permissions.")

    # 5. Non-owner cannot remove an OWNER
    if target_role_enum == OrgRole.OWNER and not can_remove_owner(actor_role_enum, current_owner_count):
        logger.warning("Non-owner %s attempted to remove OWNER %s", actor_id, target_id)
        raise GovernanceRuleViolationError("Insufficient permissions.")
