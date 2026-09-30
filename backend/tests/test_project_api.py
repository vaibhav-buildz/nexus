"""Integration tests for Project CRUD API endpoints, tenant isolation, and RBAC authorization."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import OrgRole
from app.core.security import create_access_token
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.models.user import User


# Helper functions
async def _create_user(
    db: AsyncSession,
    email: str | None = None,
    is_active: bool = True,
    is_verified: bool = True,
) -> User:
    user = User(
        email=email or f"user_{uuid.uuid4().hex[:8]}@test.internal",
        password_hash="argon2id_dummy_hash_for_tests",
        is_active=is_active,
        is_verified=is_verified,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _create_org(
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


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


# =========================================================================
# 1. Project Creation Tests
# =========================================================================


@pytest.mark.asyncio
async def test_create_project_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify successful project creation by authorized member."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    await test_db_session.commit()

    res = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={
            "name": "E-Commerce Platform",
            "slug": "e-commerce-platform",
            "description": "Core checkout and catalog service",
        },
        headers=_auth_header(owner),
    )
    assert res.status_code == 201
    data = res.json()
    assert uuid.UUID(data["id"])
    assert data["organization_id"] == str(org.id)
    assert data["name"] == "E-Commerce Platform"
    assert data["slug"] == "e-commerce-platform"
    assert data["description"] == "Core checkout and catalog service"
    assert data["is_active"] is True
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


@pytest.mark.asyncio
async def test_create_project_validation_errors(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify validation: missing name, missing slug, blank name, invalid slug formats."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    await test_db_session.commit()

    # 1. Missing name
    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"slug": "valid-slug"},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "VALIDATION_ERROR"

    # 2. Missing slug
    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Valid Name"},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 422

    # 3. Blank/whitespace-only name
    res3 = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "   ", "slug": "valid-slug"},
        headers=_auth_header(owner),
    )
    assert res3.status_code == 422

    # 4. Invalid slugs (must reject without silent lowercase transformation)
    invalid_slugs = [
        "My Project",
        "my_project",
        "my project",
        "-ecommerce",
        "ecommerce-",
        "UPPERCASE",
        "bad--slug",
        "slug with spaces",
    ]
    for bad_slug in invalid_slugs:
        res = await client.post(
            f"/api/v1/organizations/{org.id}/projects",
            json={"name": "Project Name", "slug": bad_slug},
            headers=_auth_header(owner),
        )
        assert res.status_code == 422, f"Expected 422 for slug '{bad_slug}'"


@pytest.mark.asyncio
async def test_create_project_extra_fields_forbidden(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that clients cannot override organization_id, is_active, or id."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    await test_db_session.commit()

    fake_org_id = str(uuid.uuid4())
    fake_project_id = str(uuid.uuid4())

    # Attempt to pass organization_id
    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={
            "name": "Project",
            "slug": "project-slug",
            "organization_id": fake_org_id,
        },
        headers=_auth_header(owner),
    )
    assert res1.status_code == 422

    # Attempt to pass is_active
    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={
            "name": "Project",
            "slug": "project-slug",
            "is_active": False,
        },
        headers=_auth_header(owner),
    )
    assert res2.status_code == 422

    # Attempt to pass id
    res3 = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={
            "name": "Project",
            "slug": "project-slug",
            "id": fake_project_id,
        },
        headers=_auth_header(owner),
    )
    assert res3.status_code == 422


@pytest.mark.asyncio
async def test_create_project_duplicate_slug_conflict(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify duplicate slug within same organization returns 409 Conflict."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    await test_db_session.commit()

    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "First Project", "slug": "shared-slug"},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 201

    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Second Project", "slug": "shared-slug"},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "PROJECT_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_same_slug_different_organizations_allowed(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify identical project slug in different organizations is allowed."""
    user = await _create_user(test_db_session)
    org_a = await _create_org(test_db_session, slug="org-a")
    org_b = await _create_org(test_db_session, slug="org-b")
    await _add_member(test_db_session, org_a, user, OrgRole.OWNER)
    await _add_member(test_db_session, org_b, user, OrgRole.OWNER)
    await test_db_session.commit()

    res_a = await client.post(
        f"/api/v1/organizations/{org_a.id}/projects",
        json={"name": "Org A Project", "slug": "common-slug"},
        headers=_auth_header(user),
    )
    assert res_a.status_code == 201

    res_b = await client.post(
        f"/api/v1/organizations/{org_b.id}/projects",
        json={"name": "Org B Project", "slug": "common-slug"},
        headers=_auth_header(user),
    )
    assert res_b.status_code == 201

    assert res_a.json()["slug"] == res_b.json()["slug"] == "common-slug"
    assert res_a.json()["id"] != res_b.json()["id"]
    assert res_a.json()["organization_id"] != res_b.json()["organization_id"]


# =========================================================================
# 2. List Projects Tests
# =========================================================================


@pytest.mark.asyncio
async def test_list_projects_tenant_scoped(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify GET /projects returns only current organization's projects."""
    user = await _create_user(test_db_session)
    org_a = await _create_org(test_db_session, slug="tenant-a")
    org_b = await _create_org(test_db_session, slug="tenant-b")
    await _add_member(test_db_session, org_a, user, OrgRole.OWNER)
    await _add_member(test_db_session, org_b, user, OrgRole.OWNER)
    await test_db_session.commit()

    # Create 2 projects in Org A
    await client.post(
        f"/api/v1/organizations/{org_a.id}/projects",
        json={"name": "Proj A1", "slug": "proj-a1"},
        headers=_auth_header(user),
    )
    await client.post(
        f"/api/v1/organizations/{org_a.id}/projects",
        json={"name": "Proj A2", "slug": "proj-a2"},
        headers=_auth_header(user),
    )

    # Create 1 project in Org B
    await client.post(
        f"/api/v1/organizations/{org_b.id}/projects",
        json={"name": "Proj B1", "slug": "proj-b1"},
        headers=_auth_header(user),
    )

    # List Org A
    res_a = await client.get(
        f"/api/v1/organizations/{org_a.id}/projects",
        headers=_auth_header(user),
    )
    assert res_a.status_code == 200
    slugs_a = [p["slug"] for p in res_a.json()]
    assert slugs_a == ["proj-a1", "proj-a2"]

    # List Org B
    res_b = await client.get(
        f"/api/v1/organizations/{org_b.id}/projects",
        headers=_auth_header(user),
    )
    assert res_b.status_code == 200
    slugs_b = [p["slug"] for p in res_b.json()]
    assert slugs_b == ["proj-b1"]


@pytest.mark.asyncio
async def test_list_projects_empty(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify empty organization returns empty list."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.VIEWER)
    await test_db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    assert res.json() == []


# =========================================================================
# 3. Get Project Tests & IDOR Protection
# =========================================================================


@pytest.mark.asyncio
async def test_get_project_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify retrieving project details by ID within organization."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.MEMBER)
    await test_db_session.commit()

    create_res = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Alpha Service", "slug": "alpha-service", "description": "Core"},
        headers=_auth_header(user),
    )
    project_id = create_res.json()["id"]

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project_id}",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == project_id
    assert data["name"] == "Alpha Service"
    assert data["slug"] == "alpha-service"
    assert data["description"] == "Core"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_get_nonexistent_project_returns_404(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify non-existent project returns 404."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.VIEWER)
    await test_db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{uuid.uuid4()}",
        headers=_auth_header(user),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_idor_cross_tenant_project_access_blocked(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Explicit IDOR test: User in Org A cannot read, update, or delete Project in Org B."""
    user_a = await _create_user(test_db_session, "user_a@nexus.internal")
    user_b = await _create_user(test_db_session, "user_b@nexus.internal")
    org_a = await _create_org(test_db_session, slug="org-alpha-idor")
    org_b = await _create_org(test_db_session, slug="org-beta-idor")
    await _add_member(test_db_session, org_a, user_a, OrgRole.OWNER)
    await _add_member(test_db_session, org_b, user_b, OrgRole.OWNER)
    await test_db_session.commit()

    # User B creates Project B in Org B
    res_pb = await client.post(
        f"/api/v1/organizations/{org_b.id}/projects",
        json={"name": "Project B", "slug": "project-b"},
        headers=_auth_header(user_b),
    )
    proj_b_id = res_pb.json()["id"]

    # 1. User A tries to GET Project B using Org A URL -> 404 (does not disclose existence)
    res_get_a = await client.get(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_b_id}",
        headers=_auth_header(user_a),
    )
    assert res_get_a.status_code == 404
    assert res_get_a.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    # 2. User A tries to PATCH Project B using Org A URL -> 404
    res_patch_a = await client.patch(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_b_id}",
        json={"name": "Hacked Name"},
        headers=_auth_header(user_a),
    )
    assert res_patch_a.status_code == 404
    assert res_patch_a.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    # 3. User A tries to DELETE Project B using Org A URL -> 404
    res_del_a = await client.delete(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_b_id}",
        headers=_auth_header(user_a),
    )
    assert res_del_a.status_code == 404
    assert res_del_a.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    # 4. User A tries to access Project B directly using Org B URL -> 404 (non-member of Org B)
    res_get_b = await client.get(
        f"/api/v1/organizations/{org_b.id}/projects/{proj_b_id}",
        headers=_auth_header(user_a),
    )
    assert res_get_b.status_code == 404
    assert res_get_b.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"


# =========================================================================
# 4. Update Project Tests
# =========================================================================


@pytest.mark.asyncio
async def test_update_project_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify updating name, slug, description, and partial updates."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.ADMIN)
    await test_db_session.commit()

    create_res = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Original Name", "slug": "orig-slug", "description": "Orig desc"},
        headers=_auth_header(user),
    )
    proj_id = create_res.json()["id"]

    # 1. Update name only
    res1 = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{proj_id}",
        json={"name": "Updated Name"},
        headers=_auth_header(user),
    )
    assert res1.status_code == 200
    assert res1.json()["name"] == "Updated Name"
    assert res1.json()["slug"] == "orig-slug"
    assert res1.json()["description"] == "Orig desc"

    # 2. Update slug and description
    res2 = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{proj_id}",
        json={"slug": "new-slug", "description": "New description"},
        headers=_auth_header(user),
    )
    assert res2.status_code == 200
    assert res2.json()["slug"] == "new-slug"
    assert res2.json()["description"] == "New description"

    # 3. Empty update body returns project without errors
    res3 = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{proj_id}",
        json={},
        headers=_auth_header(user),
    )
    assert res3.status_code == 200
    assert res3.json()["slug"] == "new-slug"


@pytest.mark.asyncio
async def test_update_project_duplicate_slug_conflict(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify renaming a project to an existing slug in the same organization returns 409."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    await test_db_session.commit()

    await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Project 1", "slug": "project-one"},
        headers=_auth_header(user),
    )
    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Project 2", "slug": "project-two"},
        headers=_auth_header(user),
    )
    proj2_id = res2.json()["id"]

    # Attempt to change project 2's slug to project 1's slug
    res_conflict = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{proj2_id}",
        json={"slug": "project-one"},
        headers=_auth_header(user),
    )
    assert res_conflict.status_code == 409
    assert res_conflict.json()["error"]["code"] == "PROJECT_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_update_inactive_project_rejected(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify updates to inactive projects are rejected."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    await test_db_session.commit()

    res = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Active Project", "slug": "active-project"},
        headers=_auth_header(user),
    )
    proj_id = res.json()["id"]

    # Delete (deactivate)
    del_res = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{proj_id}",
        headers=_auth_header(user),
    )
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False

    # Attempt to update inactive project
    patch_res = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{proj_id}",
        json={"name": "New Name"},
        headers=_auth_header(user),
    )
    assert patch_res.status_code == 400
    assert patch_res.json()["error"]["code"] == "PROJECT_INACTIVE"


# =========================================================================
# 5. Delete (Soft Deactivation) Tests
# =========================================================================


@pytest.mark.asyncio
async def test_delete_project_soft_deactivation(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify DELETE performs soft-deactivation (is_active=False) preserving DB row."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    await test_db_session.commit()

    res = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Deactivate Target", "slug": "deactivate-target"},
        headers=_auth_header(owner),
    )
    proj_id = uuid.UUID(res.json()["id"])

    del_res = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{proj_id}",
        headers=_auth_header(owner),
    )
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False

    # Confirm row still exists in database
    db_proj = await test_db_session.scalar(select(Project).where(Project.id == proj_id))
    assert db_proj is not None
    assert db_proj.is_active is False
    assert db_proj.name == "Deactivate Target"

    # Idempotent delete on already inactive project succeeds
    del_res2 = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{proj_id}",
        headers=_auth_header(owner),
    )
    assert del_res2.status_code == 200
    assert del_res2.json()["is_active"] is False


# =========================================================================
# 6. Role Matrix Tests (OWNER, ADMIN, MEMBER, VIEWER)
# =========================================================================


@pytest.mark.asyncio
async def test_project_api_role_matrix(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify exact role permissions across all 5 endpoints:
    OWNER: full access (create, read, update, delete)
    ADMIN: full access (create, read, update, delete)
    MEMBER: create, read, update allowed; delete denied
    VIEWER: read allowed; create, update, delete denied
    """
    owner = await _create_user(test_db_session, "owner@role.internal")
    admin = await _create_user(test_db_session, "admin@role.internal")
    member = await _create_user(test_db_session, "member@role.internal")
    viewer = await _create_user(test_db_session, "viewer@role.internal")
    org = await _create_org(test_db_session, slug="role-matrix-org")

    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    await _add_member(test_db_session, org, admin, OrgRole.ADMIN)
    await _add_member(test_db_session, org, member, OrgRole.MEMBER)
    await _add_member(test_db_session, org, viewer, OrgRole.VIEWER)
    await test_db_session.commit()

    # 1. Create endpoint
    # VIEWER cannot create -> 403
    res_v_create = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Viewer Proj", "slug": "viewer-proj"},
        headers=_auth_header(viewer),
    )
    assert res_v_create.status_code == 403
    assert res_v_create.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # MEMBER can create -> 201
    res_m_create = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Member Proj", "slug": "member-proj"},
        headers=_auth_header(member),
    )
    assert res_m_create.status_code == 201
    m_proj_id = res_m_create.json()["id"]

    # ADMIN can create -> 201
    res_a_create = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Admin Proj", "slug": "admin-proj"},
        headers=_auth_header(admin),
    )
    assert res_a_create.status_code == 201
    a_proj_id = res_a_create.json()["id"]

    # OWNER can create -> 201
    res_o_create = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Owner Proj", "slug": "owner-proj"},
        headers=_auth_header(owner),
    )
    assert res_o_create.status_code == 201
    o_proj_id = res_o_create.json()["id"]

    # 2. List endpoint: all 4 roles allowed -> 200
    for u in (viewer, member, admin, owner):
        res_list = await client.get(
            f"/api/v1/organizations/{org.id}/projects",
            headers=_auth_header(u),
        )
        assert res_list.status_code == 200
        assert len(res_list.json()) == 3

    # 3. Get endpoint: all 4 roles allowed -> 200
    for u in (viewer, member, admin, owner):
        res_get = await client.get(
            f"/api/v1/organizations/{org.id}/projects/{m_proj_id}",
            headers=_auth_header(u),
        )
        assert res_get.status_code == 200

    # 4. Update endpoint
    # VIEWER cannot update -> 403
    res_v_update = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{m_proj_id}",
        json={"name": "Viewer Edited"},
        headers=_auth_header(viewer),
    )
    assert res_v_update.status_code == 403

    # MEMBER can update -> 200
    res_m_update = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{m_proj_id}",
        json={"name": "Member Edited"},
        headers=_auth_header(member),
    )
    assert res_m_update.status_code == 200

    # ADMIN can update -> 200
    res_a_update = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{m_proj_id}",
        json={"name": "Admin Edited"},
        headers=_auth_header(admin),
    )
    assert res_a_update.status_code == 200

    # OWNER can update -> 200
    res_o_update = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{m_proj_id}",
        json={"name": "Owner Edited"},
        headers=_auth_header(owner),
    )
    assert res_o_update.status_code == 200

    # 5. Delete endpoint
    # VIEWER cannot delete -> 403
    res_v_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{m_proj_id}",
        headers=_auth_header(viewer),
    )
    assert res_v_del.status_code == 403

    # MEMBER cannot delete -> 403
    res_m_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{m_proj_id}",
        headers=_auth_header(member),
    )
    assert res_m_del.status_code == 403

    # ADMIN can delete -> 200
    res_a_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{a_proj_id}",
        headers=_auth_header(admin),
    )
    assert res_a_del.status_code == 200
    assert res_a_del.json()["is_active"] is False

    # OWNER can delete -> 200
    res_o_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{o_proj_id}",
        headers=_auth_header(owner),
    )
    assert res_o_del.status_code == 200
    assert res_o_del.json()["is_active"] is False


# =========================================================================
# 7. Inactive Organization & Unauthenticated / Unverified Access
# =========================================================================


@pytest.mark.asyncio
async def test_project_operations_on_inactive_organization_forbidden(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify operations on an inactive organization return 403 ORGANIZATION_INACTIVE."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session, is_active=False)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    await test_db_session.commit()

    # Create project against inactive org -> 403
    res_create = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        json={"name": "Proj", "slug": "proj"},
        headers=_auth_header(user),
    )
    assert res_create.status_code == 403
    assert res_create.json()["error"]["code"] == "ORGANIZATION_INACTIVE"

    # List projects against inactive org -> 403
    res_list = await client.get(
        f"/api/v1/organizations/{org.id}/projects",
        headers=_auth_header(user),
    )
    assert res_list.status_code == 403
    assert res_list.json()["error"]["code"] == "ORGANIZATION_INACTIVE"


@pytest.mark.asyncio
async def test_project_endpoints_unauthenticated_and_unverified(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify unauthenticated requests return 401 and unverified users return 403."""
    org = await _create_org(test_db_session)
    unverified_user = await _create_user(test_db_session, is_verified=False)
    await _add_member(test_db_session, org, unverified_user, OrgRole.OWNER)
    await test_db_session.commit()

    # 1. Unauthenticated -> 401
    res_unauth = await client.get(f"/api/v1/organizations/{org.id}/projects")
    assert res_unauth.status_code == 401

    # 2. Unverified user -> 403 FORBIDDEN
    res_unver = await client.get(
        f"/api/v1/organizations/{org.id}/projects",
        headers=_auth_header(unverified_user),
    )
    assert res_unver.status_code == 403
