"""Unit and integration tests for Phase 3 RBAC permissions and authorization dependencies."""

from typing import Annotated
import uuid
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
    register_error_handlers,
)
from app.core.rbac import (
    OrgRole,
    Permission,
    has_permission,
)
from app.core.security import create_access_token
from app.db.session import get_db_session
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


# =========================================================================
# 1. Unit Tests for Pure Permission Matrix
# =========================================================================


def test_project_permissions_matrix():
    """Verify exact permission matrix for project:* across all 4 roles."""
    perms = [
        Permission.PROJECT_READ,
        Permission.PROJECT_CREATE,
        Permission.PROJECT_UPDATE,
        Permission.PROJECT_DELETE,
    ]

    # VIEWER: read allowed; create/update/delete denied
    assert has_permission(OrgRole.VIEWER, Permission.PROJECT_READ) is True
    assert has_permission(OrgRole.VIEWER, Permission.PROJECT_CREATE) is False
    assert has_permission(OrgRole.VIEWER, Permission.PROJECT_UPDATE) is False
    assert has_permission(OrgRole.VIEWER, Permission.PROJECT_DELETE) is False

    # Also test string-based checks
    assert has_permission("VIEWER", "project:read") is True
    assert has_permission("VIEWER", "project:create") is False
    assert has_permission("VIEWER", "project:update") is False
    assert has_permission("VIEWER", "project:delete") is False

    # MEMBER: read/create/update allowed; delete denied
    assert has_permission(OrgRole.MEMBER, Permission.PROJECT_READ) is True
    assert has_permission(OrgRole.MEMBER, Permission.PROJECT_CREATE) is True
    assert has_permission(OrgRole.MEMBER, Permission.PROJECT_UPDATE) is True
    assert has_permission(OrgRole.MEMBER, Permission.PROJECT_DELETE) is False

    assert has_permission("MEMBER", "project:read") is True
    assert has_permission("MEMBER", "project:create") is True
    assert has_permission("MEMBER", "project:update") is True
    assert has_permission("MEMBER", "project:delete") is False

    # ADMIN: all allowed
    for p in perms:
        assert has_permission(OrgRole.ADMIN, p) is True
        assert has_permission("ADMIN", p.value) is True

    # OWNER: all allowed
    for p in perms:
        assert has_permission(OrgRole.OWNER, p) is True
        assert has_permission("OWNER", p.value) is True


def test_environment_permissions_matrix():
    """Verify exact permission matrix for environment:* across all 4 roles."""
    perms = [
        Permission.ENVIRONMENT_READ,
        Permission.ENVIRONMENT_CREATE,
        Permission.ENVIRONMENT_UPDATE,
        Permission.ENVIRONMENT_DELETE,
    ]

    # VIEWER: read allowed; create/update/delete denied
    assert has_permission(OrgRole.VIEWER, Permission.ENVIRONMENT_READ) is True
    assert has_permission(OrgRole.VIEWER, Permission.ENVIRONMENT_CREATE) is False
    assert has_permission(OrgRole.VIEWER, Permission.ENVIRONMENT_UPDATE) is False
    assert has_permission(OrgRole.VIEWER, Permission.ENVIRONMENT_DELETE) is False

    assert has_permission("VIEWER", "environment:read") is True
    assert has_permission("VIEWER", "environment:create") is False
    assert has_permission("VIEWER", "environment:update") is False
    assert has_permission("VIEWER", "environment:delete") is False

    # MEMBER: read/create/update allowed; delete denied
    assert has_permission(OrgRole.MEMBER, Permission.ENVIRONMENT_READ) is True
    assert has_permission(OrgRole.MEMBER, Permission.ENVIRONMENT_CREATE) is True
    assert has_permission(OrgRole.MEMBER, Permission.ENVIRONMENT_UPDATE) is True
    assert has_permission(OrgRole.MEMBER, Permission.ENVIRONMENT_DELETE) is False

    assert has_permission("MEMBER", "environment:read") is True
    assert has_permission("MEMBER", "environment:create") is True
    assert has_permission("MEMBER", "environment:update") is True
    assert has_permission("MEMBER", "environment:delete") is False

    # ADMIN: all allowed
    for p in perms:
        assert has_permission(OrgRole.ADMIN, p) is True
        assert has_permission("ADMIN", p.value) is True

    # OWNER: all allowed
    for p in perms:
        assert has_permission(OrgRole.OWNER, p) is True
        assert has_permission("OWNER", p.value) is True


def test_service_permissions_matrix():
    """Verify exact permission matrix for service:* across all 4 roles."""
    perms = [
        Permission.SERVICE_READ,
        Permission.SERVICE_CREATE,
        Permission.SERVICE_UPDATE,
        Permission.SERVICE_DELETE,
    ]

    # VIEWER: read allowed; create/update/delete denied
    assert has_permission(OrgRole.VIEWER, Permission.SERVICE_READ) is True
    assert has_permission(OrgRole.VIEWER, Permission.SERVICE_CREATE) is False
    assert has_permission(OrgRole.VIEWER, Permission.SERVICE_UPDATE) is False
    assert has_permission(OrgRole.VIEWER, Permission.SERVICE_DELETE) is False

    assert has_permission("VIEWER", "service:read") is True
    assert has_permission("VIEWER", "service:create") is False
    assert has_permission("VIEWER", "service:update") is False
    assert has_permission("VIEWER", "service:delete") is False

    # MEMBER: read/create/update allowed; delete denied
    assert has_permission(OrgRole.MEMBER, Permission.SERVICE_READ) is True
    assert has_permission(OrgRole.MEMBER, Permission.SERVICE_CREATE) is True
    assert has_permission(OrgRole.MEMBER, Permission.SERVICE_UPDATE) is True
    assert has_permission(OrgRole.MEMBER, Permission.SERVICE_DELETE) is False

    assert has_permission("MEMBER", "service:read") is True
    assert has_permission("MEMBER", "service:create") is True
    assert has_permission("MEMBER", "service:update") is True
    assert has_permission("MEMBER", "service:delete") is False

    # ADMIN: all allowed
    for p in perms:
        assert has_permission(OrgRole.ADMIN, p) is True
        assert has_permission("ADMIN", p.value) is True

    # OWNER: all allowed
    for p in perms:
        assert has_permission(OrgRole.OWNER, p) is True
        assert has_permission("OWNER", p.value) is True


# =========================================================================
# 2. Integration Tests via HTTP Dependency Pipeline
# =========================================================================

phase3_test_router = APIRouter(prefix="/api/v1/organizations/{org_id}")

# Project routes
@phase3_test_router.get("/projects")
async def handle_project_read(
    member: Annotated[OrganizationMember, Depends(require_permission("project:read"))],
):
    return {"status": "ok", "role": member.role}


@phase3_test_router.post("/projects")
async def handle_project_create(
    member: Annotated[OrganizationMember, Depends(require_permission("project:create"))],
):
    return {"status": "ok", "role": member.role}


@phase3_test_router.put("/projects/{project_id}")
async def handle_project_update(
    member: Annotated[OrganizationMember, Depends(require_permission("project:update"))],
):
    return {"status": "ok", "role": member.role}


@phase3_test_router.delete("/projects/{project_id}")
async def handle_project_delete(
    member: Annotated[OrganizationMember, Depends(require_permission("project:delete"))],
):
    return {"status": "ok", "role": member.role}


# Environment routes
@phase3_test_router.get("/environments")
async def handle_environment_read(
    member: Annotated[OrganizationMember, Depends(require_permission("environment:read"))],
):
    return {"status": "ok", "role": member.role}


@phase3_test_router.post("/environments")
async def handle_environment_create(
    member: Annotated[OrganizationMember, Depends(require_permission("environment:create"))],
):
    return {"status": "ok", "role": member.role}


@phase3_test_router.put("/environments/{env_id}")
async def handle_environment_update(
    member: Annotated[OrganizationMember, Depends(require_permission("environment:update"))],
):
    return {"status": "ok", "role": member.role}


@phase3_test_router.delete("/environments/{env_id}")
async def handle_environment_delete(
    member: Annotated[OrganizationMember, Depends(require_permission("environment:delete"))],
):
    return {"status": "ok", "role": member.role}


# Service routes
@phase3_test_router.get("/services")
async def handle_service_read(
    member: Annotated[OrganizationMember, Depends(require_permission("service:read"))],
):
    return {"status": "ok", "role": member.role}


@phase3_test_router.post("/services")
async def handle_service_create(
    member: Annotated[OrganizationMember, Depends(require_permission("service:create"))],
):
    return {"status": "ok", "role": member.role}


@phase3_test_router.put("/services/{service_id}")
async def handle_service_update(
    member: Annotated[OrganizationMember, Depends(require_permission("service:update"))],
):
    return {"status": "ok", "role": member.role}


@phase3_test_router.delete("/services/{service_id}")
async def handle_service_delete(
    member: Annotated[OrganizationMember, Depends(require_permission("service:delete"))],
):
    return {"status": "ok", "role": member.role}


@pytest_asyncio.fixture
async def p3_rbac_client(test_db_session: AsyncSession) -> AsyncClient:
    """Create test HTTP client mounting Phase 3 test routes with real error handlers."""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(phase3_test_router)

    async def override_get_db_session():
        yield test_db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _setup_org_with_members(db: AsyncSession):
    org = Organization(name="P3 Auth Test Org", slug=f"p3-org-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()

    users = {}
    for role in OrgRole:
        user = User(
            email=f"{role.value.lower()}_{uuid.uuid4().hex[:6]}@nexus.internal",
            password_hash="argon2id_dummy_hash",
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        await db.flush()
        member = OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value)
        db.add(member)
        await db.flush()
        users[role] = user

    await db.commit()
    await db.refresh(org)
    return org, users


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_project_authorization_pipeline_http(
    test_db_session: AsyncSession,
    p3_rbac_client: AsyncClient,
):
    """Verify require_permission('project:*') enforcement on HTTP pipeline."""
    org, users = await _setup_org_with_members(test_db_session)
    pid = uuid.uuid4()

    viewer = users[OrgRole.VIEWER]
    member = users[OrgRole.MEMBER]
    admin = users[OrgRole.ADMIN]
    owner = users[OrgRole.OWNER]

    # 1. project:read -> VIEWER, MEMBER, ADMIN, OWNER allowed
    for u in (viewer, member, admin, owner):
        res = await p3_rbac_client.get(
            f"/api/v1/organizations/{org.id}/projects",
            headers=_auth_header(u),
        )
        assert res.status_code == 200

    # 2. project:create -> VIEWER denied; MEMBER, ADMIN, OWNER allowed
    res_v = await p3_rbac_client.post(
        f"/api/v1/organizations/{org.id}/projects",
        headers=_auth_header(viewer),
    )
    assert res_v.status_code == 403
    assert res_v.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    for u in (member, admin, owner):
        res = await p3_rbac_client.post(
            f"/api/v1/organizations/{org.id}/projects",
            headers=_auth_header(u),
        )
        assert res.status_code == 200

    # 3. project:update -> VIEWER denied; MEMBER, ADMIN, OWNER allowed
    res_v_put = await p3_rbac_client.put(
        f"/api/v1/organizations/{org.id}/projects/{pid}",
        headers=_auth_header(viewer),
    )
    assert res_v_put.status_code == 403

    for u in (member, admin, owner):
        res = await p3_rbac_client.put(
            f"/api/v1/organizations/{org.id}/projects/{pid}",
            headers=_auth_header(u),
        )
        assert res.status_code == 200

    # 4. project:delete -> VIEWER, MEMBER denied; ADMIN, OWNER allowed
    for u in (viewer, member):
        res = await p3_rbac_client.delete(
            f"/api/v1/organizations/{org.id}/projects/{pid}",
            headers=_auth_header(u),
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    for u in (admin, owner):
        res = await p3_rbac_client.delete(
            f"/api/v1/organizations/{org.id}/projects/{pid}",
            headers=_auth_header(u),
        )
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_environment_authorization_pipeline_http(
    test_db_session: AsyncSession,
    p3_rbac_client: AsyncClient,
):
    """Verify require_permission('environment:*') enforcement on HTTP pipeline."""
    org, users = await _setup_org_with_members(test_db_session)
    eid = uuid.uuid4()

    viewer = users[OrgRole.VIEWER]
    member = users[OrgRole.MEMBER]
    admin = users[OrgRole.ADMIN]
    owner = users[OrgRole.OWNER]

    # 1. environment:read -> All allowed
    for u in (viewer, member, admin, owner):
        res = await p3_rbac_client.get(
            f"/api/v1/organizations/{org.id}/environments",
            headers=_auth_header(u),
        )
        assert res.status_code == 200

    # 2. environment:create -> VIEWER denied; MEMBER, ADMIN, OWNER allowed
    res_v = await p3_rbac_client.post(
        f"/api/v1/organizations/{org.id}/environments",
        headers=_auth_header(viewer),
    )
    assert res_v.status_code == 403

    for u in (member, admin, owner):
        res = await p3_rbac_client.post(
            f"/api/v1/organizations/{org.id}/environments",
            headers=_auth_header(u),
        )
        assert res.status_code == 200

    # 3. environment:update -> VIEWER denied; MEMBER, ADMIN, OWNER allowed
    res_v_put = await p3_rbac_client.put(
        f"/api/v1/organizations/{org.id}/environments/{eid}",
        headers=_auth_header(viewer),
    )
    assert res_v_put.status_code == 403

    for u in (member, admin, owner):
        res = await p3_rbac_client.put(
            f"/api/v1/organizations/{org.id}/environments/{eid}",
            headers=_auth_header(u),
        )
        assert res.status_code == 200

    # 4. environment:delete -> VIEWER, MEMBER denied; ADMIN, OWNER allowed
    for u in (viewer, member):
        res = await p3_rbac_client.delete(
            f"/api/v1/organizations/{org.id}/environments/{eid}",
            headers=_auth_header(u),
        )
        assert res.status_code == 403

    for u in (admin, owner):
        res = await p3_rbac_client.delete(
            f"/api/v1/organizations/{org.id}/environments/{eid}",
            headers=_auth_header(u),
        )
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_service_authorization_pipeline_http(
    test_db_session: AsyncSession,
    p3_rbac_client: AsyncClient,
):
    """Verify require_permission('service:*') enforcement on HTTP pipeline."""
    org, users = await _setup_org_with_members(test_db_session)
    sid = uuid.uuid4()

    viewer = users[OrgRole.VIEWER]
    member = users[OrgRole.MEMBER]
    admin = users[OrgRole.ADMIN]
    owner = users[OrgRole.OWNER]

    # 1. service:read -> All allowed
    for u in (viewer, member, admin, owner):
        res = await p3_rbac_client.get(
            f"/api/v1/organizations/{org.id}/services",
            headers=_auth_header(u),
        )
        assert res.status_code == 200

    # 2. service:create -> VIEWER denied; MEMBER, ADMIN, OWNER allowed
    res_v = await p3_rbac_client.post(
        f"/api/v1/organizations/{org.id}/services",
        headers=_auth_header(viewer),
    )
    assert res_v.status_code == 403

    for u in (member, admin, owner):
        res = await p3_rbac_client.post(
            f"/api/v1/organizations/{org.id}/services",
            headers=_auth_header(u),
        )
        assert res.status_code == 200

    # 3. service:update -> VIEWER denied; MEMBER, ADMIN, OWNER allowed
    res_v_put = await p3_rbac_client.put(
        f"/api/v1/organizations/{org.id}/services/{sid}",
        headers=_auth_header(viewer),
    )
    assert res_v_put.status_code == 403

    for u in (member, admin, owner):
        res = await p3_rbac_client.put(
            f"/api/v1/organizations/{org.id}/services/{sid}",
            headers=_auth_header(u),
        )
        assert res.status_code == 200

    # 4. service:delete -> VIEWER, MEMBER denied; ADMIN, OWNER allowed
    for u in (viewer, member):
        res = await p3_rbac_client.delete(
            f"/api/v1/organizations/{org.id}/services/{sid}",
            headers=_auth_header(u),
        )
        assert res.status_code == 403

    for u in (admin, owner):
        res = await p3_rbac_client.delete(
            f"/api/v1/organizations/{org.id}/services/{sid}",
            headers=_auth_header(u),
        )
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_tenant_boundary_on_phase3_permissions(
    test_db_session: AsyncSession,
    p3_rbac_client: AsyncClient,
):
    """Verify tenant boundary: user privileges in Org A do not grant access to Org B."""
    org_a, users_a = await _setup_org_with_members(test_db_session)
    org_b, users_b = await _setup_org_with_members(test_db_session)

    owner_a = users_a[OrgRole.OWNER]

    # Owner of Org A attempts to access Org B's project endpoint
    res = await p3_rbac_client.get(
        f"/api/v1/organizations/{org_b.id}/projects",
        headers=_auth_header(owner_a),
    )
    # 404 returned for non-member to avoid tenant enumeration
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"
