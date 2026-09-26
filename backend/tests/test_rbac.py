"""Integration and unit tests for NEXUS RBAC, governance rules, and organization authorization dependencies."""

from datetime import timedelta
import uuid
from typing import Annotated
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_org_membership,
    get_current_user,
    get_organization_context,
    require_permission,
)
from app.core.errors import (
    GovernanceRuleViolationError,
    InactiveOrganizationError,
    InactiveUserError,
    InsufficientPermissionsError,
    NotAnOrganizationMemberError,
    OrganizationNotFoundError,
    register_error_handlers,
)
from app.core.rbac import (
    OrgRole,
    Permission,
    ROLE_PERMISSIONS,
    can_demote_owner,
    can_modify_owner_role,
    can_promote_to_owner,
    can_remove_owner,
    has_permission,
    is_last_owner,
    is_self_escalation,
    validate_member_removal,
    validate_organization_membership,
    validate_role_assignment,
)
from app.core.security import create_access_token
from app.db.session import get_db_session
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


# Helper functions to create test fixtures in DB
async def _create_test_user(
    db: AsyncSession,
    email: str | None = None,
    is_active: bool = True,
    is_verified: bool = True,
) -> User:
    user = User(
        email=email or f"user_{uuid.uuid4().hex[:8]}@nexus.internal",
        password_hash="argon2id_dummy_hash_for_tests",
        is_active=is_active,
        is_verified=is_verified,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _create_test_org(
    db: AsyncSession,
    slug: str | None = None,
    is_active: bool = True,
) -> Organization:
    org = Organization(
        name="Test Org",
        slug=slug or f"org-{uuid.uuid4().hex[:8]}",
        is_active=is_active,
    )
    db.add(org)
    await db.flush()
    await db.refresh(org)
    return org


async def _add_member(
    db: AsyncSession,
    org: Organization,
    user: User,
    role: OrgRole,
) -> OrganizationMember:
    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=role.value,
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    return member


# Define a temporary router using dependencies for testing
rbac_test_router = APIRouter(prefix="/api/v1/organizations/{org_id}")


@rbac_test_router.get("/context-only")
async def handle_context_endpoint(
    org: Annotated[Organization, Depends(get_organization_context)],
):
    return {"org_id": str(org.id), "is_active": org.is_active}


@rbac_test_router.get("/membership")
async def handle_membership_endpoint(
    member: Annotated[OrganizationMember, Depends(get_current_org_membership)],
):
    return {
        "user_id": str(member.user_id),
        "org_id": str(member.organization_id),
        "role": member.role,
    }


@rbac_test_router.get("/org-read")
async def handle_org_read_endpoint(
    member: Annotated[OrganizationMember, Depends(require_permission(Permission.ORG_READ))],
):
    return {"status": "ok", "role": member.role}


@rbac_test_router.put("/org-update")
async def handle_org_update_endpoint(
    member: Annotated[OrganizationMember, Depends(require_permission(Permission.ORG_UPDATE))],
):
    return {"status": "ok", "role": member.role}


@rbac_test_router.delete("/org-delete")
async def handle_org_delete_endpoint(
    member: Annotated[OrganizationMember, Depends(require_permission(Permission.ORG_DELETE))],
):
    return {"status": "ok", "role": member.role}


@rbac_test_router.post("/member-invite")
async def handle_member_invite_endpoint(
    member: Annotated[OrganizationMember, Depends(require_permission(Permission.MEMBER_INVITE))],
):
    return {"status": "ok", "role": member.role}


@pytest_asyncio.fixture
async def rbac_client(
    test_db_session: AsyncSession,
) -> AsyncClient:
    """Create test HTTP client mounting test RBAC endpoints with real exception handlers."""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(rbac_test_router)

    async def override_get_db_session():
        yield test_db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# =========================================================================
# 1. Permission Matrix & Pure RBAC Unit Tests
# =========================================================================


def test_permission_matrix_viewer():
    """VIEWER permissions: org:read, member:read, resource:read."""
    allowed = {
        Permission.ORG_READ,
        Permission.MEMBER_READ,
        Permission.RESOURCE_READ,
    }
    for perm in Permission:
        expected = perm in allowed
        assert has_permission(OrgRole.VIEWER, perm) is expected
        assert has_permission(OrgRole.VIEWER.value, perm.value) is expected


def test_permission_matrix_member():
    """MEMBER permissions: VIEWER + resource:create, resource:update."""
    allowed = {
        Permission.ORG_READ,
        Permission.MEMBER_READ,
        Permission.RESOURCE_READ,
        Permission.RESOURCE_CREATE,
        Permission.RESOURCE_UPDATE,
    }
    for perm in Permission:
        expected = perm in allowed
        assert has_permission(OrgRole.MEMBER, perm) is expected


def test_permission_matrix_admin():
    """ADMIN permissions: all MEMBER + org:update, member:invite, member:role_update, member:remove, resource:delete."""
    allowed = {
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
    }
    for perm in Permission:
        expected = perm in allowed
        assert has_permission(OrgRole.ADMIN, perm) is expected

    # ADMIN must NOT have org:delete
    assert has_permission(OrgRole.ADMIN, Permission.ORG_DELETE) is False


def test_permission_matrix_owner():
    """OWNER permissions: all permissions including org:delete."""
    for perm in Permission:
        assert has_permission(OrgRole.OWNER, perm) is True


# =========================================================================
# 2. Explicit Governance Rules Unit Tests
# =========================================================================


def test_admin_cannot_promote_to_owner():
    """ADMIN cannot create/promote an OWNER."""
    actor_id = uuid.uuid4()
    target_id = uuid.uuid4()

    assert can_promote_to_owner(OrgRole.ADMIN) is False
    assert can_promote_to_owner(OrgRole.MEMBER) is False
    assert can_promote_to_owner(OrgRole.VIEWER) is False
    assert can_promote_to_owner(OrgRole.OWNER) is True

    # Validate assignment rejection
    with pytest.raises(GovernanceRuleViolationError):
        validate_role_assignment(
            actor_id=actor_id,
            actor_role=OrgRole.ADMIN,
            target_id=target_id,
            target_current_role=OrgRole.MEMBER,
            target_new_role=OrgRole.OWNER,
        )


def test_admin_cannot_modify_or_demote_owner():
    """ADMIN cannot demote/remove an OWNER, or modify another OWNER's role."""
    actor_id = uuid.uuid4()
    target_id = uuid.uuid4()

    assert can_modify_owner_role(OrgRole.ADMIN) is False
    assert can_modify_owner_role(OrgRole.OWNER) is True

    # Modifying role
    with pytest.raises(GovernanceRuleViolationError):
        validate_role_assignment(
            actor_id=actor_id,
            actor_role=OrgRole.ADMIN,
            target_id=target_id,
            target_current_role=OrgRole.OWNER,
            target_new_role=OrgRole.ADMIN,
            current_owner_count=2,
        )

    # Removing owner
    with pytest.raises(GovernanceRuleViolationError):
        validate_member_removal(
            actor_id=actor_id,
            actor_role=OrgRole.ADMIN,
            target_id=target_id,
            target_role=OrgRole.OWNER,
            current_owner_count=2,
        )


def test_only_owner_can_promote_and_demote_owner():
    """Only OWNER can promote to OWNER or demote an OWNER."""
    owner_id = uuid.uuid4()
    target_id = uuid.uuid4()

    # Owner promoting Member to Owner succeeds
    validate_role_assignment(
        actor_id=owner_id,
        actor_role=OrgRole.OWNER,
        target_id=target_id,
        target_current_role=OrgRole.MEMBER,
        target_new_role=OrgRole.OWNER,
    )

    # Owner demoting Owner to Admin succeeds when multiple owners exist
    validate_role_assignment(
        actor_id=owner_id,
        actor_role=OrgRole.OWNER,
        target_id=target_id,
        target_current_role=OrgRole.OWNER,
        target_new_role=OrgRole.ADMIN,
        current_owner_count=2,
    )


def test_last_owner_protection():
    """Prevent the last OWNER from leaving, being removed, or being demoted."""
    owner_id = uuid.uuid4()
    target_id = uuid.uuid4()

    assert is_last_owner(OrgRole.OWNER, current_owner_count=1) is True
    assert is_last_owner(OrgRole.OWNER, current_owner_count=2) is False
    assert is_last_owner(OrgRole.ADMIN, current_owner_count=1) is False

    assert can_demote_owner(OrgRole.OWNER, current_owner_count=1) is False
    assert can_demote_owner(OrgRole.OWNER, current_owner_count=2) is True

    assert can_remove_owner(OrgRole.OWNER, current_owner_count=1) is False
    assert can_remove_owner(OrgRole.OWNER, current_owner_count=2) is True

    # Last owner demotion attempt
    with pytest.raises(GovernanceRuleViolationError):
        validate_role_assignment(
            actor_id=owner_id,
            actor_role=OrgRole.OWNER,
            target_id=target_id,
            target_current_role=OrgRole.OWNER,
            target_new_role=OrgRole.ADMIN,
            current_owner_count=1,
        )

    # Last owner self-leaving attempt
    with pytest.raises(GovernanceRuleViolationError):
        validate_member_removal(
            actor_id=owner_id,
            actor_role=OrgRole.OWNER,
            target_id=owner_id,  # self
            target_role=OrgRole.OWNER,
            current_owner_count=1,
        )


def test_self_privilege_escalation():
    """A user cannot escalate their own privileges."""
    user_id = uuid.uuid4()

    assert is_self_escalation(user_id, user_id, OrgRole.MEMBER, OrgRole.ADMIN) is True
    assert is_self_escalation(user_id, user_id, OrgRole.ADMIN, OrgRole.OWNER) is True
    assert is_self_escalation(user_id, user_id, OrgRole.VIEWER, OrgRole.MEMBER) is True

    # Attempting to assign higher role to oneself
    with pytest.raises(GovernanceRuleViolationError):
        validate_role_assignment(
            actor_id=user_id,
            actor_role=OrgRole.ADMIN,
            target_id=user_id,
            target_current_role=OrgRole.ADMIN,
            target_new_role=OrgRole.OWNER,
        )


def test_organization_membership_validation():
    """Membership must always belong to the organization being accessed."""
    org1_id = uuid.uuid4()
    org2_id = uuid.uuid4()

    assert validate_organization_membership(org1_id, org1_id) is True
    assert validate_organization_membership(org1_id, org2_id) is False


# =========================================================================
# 3. FastAPI Dependencies HTTP Integration Tests
# =========================================================================


@pytest.mark.asyncio
async def test_valid_membership_access(
    test_db_session: AsyncSession,
    rbac_client: AsyncClient,
):
    """Valid verified member accesses route successfully."""
    user = await _create_test_user(test_db_session)
    org = await _create_test_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.MEMBER)
    await test_db_session.commit()

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = await rbac_client.get(
        f"/api/v1/organizations/{org.id}/membership",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == str(user.id)
    assert data["org_id"] == str(org.id)
    assert data["role"] == OrgRole.MEMBER.value


@pytest.mark.asyncio
async def test_non_member_access_rejected(
    test_db_session: AsyncSession,
    rbac_client: AsyncClient,
):
    """Verified user who is not a member of the organization is rejected with 404 to prevent tenant leakage."""
    user = await _create_test_user(test_db_session)
    org = await _create_test_org(test_db_session)
    await test_db_session.commit()

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = await rbac_client.get(
        f"/api/v1/organizations/{org.id}/membership",
        headers=headers,
    )
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "ORGANIZATION_NOT_FOUND"
    assert data["error"]["message"] == "Organization not found."


@pytest.mark.asyncio
async def test_inactive_organization_non_member_access_rejected(
    test_db_session: AsyncSession,
    rbac_client: AsyncClient,
):
    """A non-member accessing an inactive organization receives 404, preventing inactive tenant discovery."""
    user = await _create_test_user(test_db_session)
    inactive_org = await _create_test_org(test_db_session, is_active=False)
    await test_db_session.commit()

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = await rbac_client.get(
        f"/api/v1/organizations/{inactive_org.id}/membership",
        headers=headers,
    )
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "ORGANIZATION_NOT_FOUND"
    assert data["error"]["message"] == "Organization not found."


@pytest.mark.asyncio
async def test_inactive_organization_rejected(
    test_db_session: AsyncSession,
    rbac_client: AsyncClient,
):
    """Accessing an inactive organization is rejected with 403."""
    user = await _create_test_user(test_db_session)
    inactive_org = await _create_test_org(test_db_session, is_active=False)
    await _add_member(test_db_session, inactive_org, user, OrgRole.OWNER)
    await test_db_session.commit()

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = await rbac_client.get(
        f"/api/v1/organizations/{inactive_org.id}/membership",
        headers=headers,
    )
    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "ORGANIZATION_INACTIVE"
    assert data["error"]["message"] == "Organization is inactive."


@pytest.mark.asyncio
async def test_non_existent_organization_rejected(
    test_db_session: AsyncSession,
    rbac_client: AsyncClient,
):
    """Accessing a non-existent organization is rejected with 404."""
    user = await _create_test_user(test_db_session)
    await test_db_session.commit()

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    non_existent_org_id = uuid.uuid4()
    response = await rbac_client.get(
        f"/api/v1/organizations/{non_existent_org_id}/membership",
        headers=headers,
    )
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "ORGANIZATION_NOT_FOUND"
    assert data["error"]["message"] == "Organization not found."


@pytest.mark.asyncio
async def test_inactive_user_rejected(
    test_db_session: AsyncSession,
    rbac_client: AsyncClient,
):
    """An inactive user attempting to access organization endpoints is rejected with 403."""
    user = await _create_test_user(test_db_session, is_active=False)
    org = await _create_test_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    await test_db_session.commit()

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = await rbac_client.get(
        f"/api/v1/organizations/{org.id}/membership",
        headers=headers,
    )
    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "USER_INACTIVE"


@pytest.mark.asyncio
async def test_unverified_user_rejected(
    test_db_session: AsyncSession,
    rbac_client: AsyncClient,
):
    """An unverified user attempting to access organization endpoints is rejected with 403."""
    user = await _create_test_user(test_db_session, is_verified=False)
    org = await _create_test_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    await test_db_session.commit()

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = await rbac_client.get(
        f"/api/v1/organizations/{org.id}/membership",
        headers=headers,
    )
    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "USER_INACTIVE"
    assert data["error"]["message"] == "Email address has not been verified."


@pytest.mark.asyncio
async def test_role_permissions_http_endpoints(
    test_db_session: AsyncSession,
    rbac_client: AsyncClient,
):
    """Test VIEWER, MEMBER, ADMIN, OWNER access against endpoints requiring specific permissions."""
    org = await _create_test_org(test_db_session)

    viewer = await _create_test_user(test_db_session, "viewer@test.com")
    member = await _create_test_user(test_db_session, "member@test.com")
    admin = await _create_test_user(test_db_session, "admin@test.com")
    owner = await _create_test_user(test_db_session, "owner@test.com")

    await _add_member(test_db_session, org, viewer, OrgRole.VIEWER)
    await _add_member(test_db_session, org, member, OrgRole.MEMBER)
    await _add_member(test_db_session, org, admin, OrgRole.ADMIN)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    await test_db_session.commit()

    def auth_header(u: User):
        token = create_access_token(subject=str(u.id))
        return {"Authorization": f"Bearer {token}"}

    # 1. org-read (VIEWER, MEMBER, ADMIN, OWNER all have org:read)
    for u in (viewer, member, admin, owner):
        res = await rbac_client.get(
            f"/api/v1/organizations/{org.id}/org-read",
            headers=auth_header(u),
        )
        assert res.status_code == 200, f"Expected 200 for {u.email}"

    # 2. member-invite (Only ADMIN, OWNER have member:invite; VIEWER, MEMBER do not)
    for u in (viewer, member):
        res = await rbac_client.post(
            f"/api/v1/organizations/{org.id}/member-invite",
            headers=auth_header(u),
        )
        assert res.status_code == 403, f"Expected 403 for {u.email}"
        assert res.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
        assert res.json()["error"]["message"] == "Insufficient permissions."

    for u in (admin, owner):
        res = await rbac_client.post(
            f"/api/v1/organizations/{org.id}/member-invite",
            headers=auth_header(u),
        )
        assert res.status_code == 200, f"Expected 200 for {u.email}"

    # 3. org-update (Only ADMIN, OWNER have org:update)
    for u in (viewer, member):
        res = await rbac_client.put(
            f"/api/v1/organizations/{org.id}/org-update",
            headers=auth_header(u),
        )
        assert res.status_code == 403

    for u in (admin, owner):
        res = await rbac_client.put(
            f"/api/v1/organizations/{org.id}/org-update",
            headers=auth_header(u),
        )
        assert res.status_code == 200

    # 4. org-delete (Only OWNER has org:delete; ADMIN, MEMBER, VIEWER do not)
    for u in (viewer, member, admin):
        res = await rbac_client.delete(
            f"/api/v1/organizations/{org.id}/org-delete",
            headers=auth_header(u),
        )
        assert res.status_code == 403, f"Expected 403 for {u.email}"
        assert res.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    res = await rbac_client.delete(
        f"/api/v1/organizations/{org.id}/org-delete",
        headers=auth_header(owner),
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_organization_context_isolation(
    test_db_session: AsyncSession,
    rbac_client: AsyncClient,
):
    """Context isolation: user privileges in Org A must not leak into Org B."""
    user = await _create_test_user(test_db_session)
    org_a = await _create_test_org(test_db_session, "org-alpha")
    org_b = await _create_test_org(test_db_session, "org-beta")

    # User is OWNER in Org A, but NOT a member of Org B
    await _add_member(test_db_session, org_a, user, OrgRole.OWNER)
    await test_db_session.commit()

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Org A: Access allowed
    res_a = await rbac_client.get(
        f"/api/v1/organizations/{org_a.id}/org-read",
        headers=headers,
    )
    assert res_a.status_code == 200

    # Org B: Access denied with 404 (non-member receives 404 to prevent tenant enumeration)
    res_b = await rbac_client.get(
        f"/api/v1/organizations/{org_b.id}/org-read",
        headers=headers,
    )
    assert res_b.status_code == 404
    assert res_b.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"

    # User added to Org B as VIEWER
    await _add_member(test_db_session, org_b, user, OrgRole.VIEWER)
    await test_db_session.commit()

    # Org B: VIEWER can read
    res_b_read = await rbac_client.get(
        f"/api/v1/organizations/{org_b.id}/org-read",
        headers=headers,
    )
    assert res_b_read.status_code == 200

    # Org B: VIEWER cannot delete org (even though user is OWNER in Org A)
    res_b_delete = await rbac_client.delete(
        f"/api/v1/organizations/{org_b.id}/org-delete",
        headers=headers,
    )
    assert res_b_delete.status_code == 403
    assert res_b_delete.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # Org A: Still can delete org
    res_a_delete = await rbac_client.delete(
        f"/api/v1/organizations/{org_a.id}/org-delete",
        headers=headers,
    )
    assert res_a_delete.status_code == 200
