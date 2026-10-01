"""Integration tests for Environment CRUD API endpoints, tenant isolation, parent hierarchy, and RBAC authorization."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import OrgRole
from app.core.security import create_access_token
from app.models.environment import Environment
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


async def _create_project(
    db: AsyncSession,
    org: Organization,
    slug: str | None = None,
    is_active: bool = True,
) -> Project:
    project = Project(
        organization_id=org.id,
        name="Test Project",
        slug=slug or f"proj-{uuid.uuid4().hex[:8]}",
        description="Project description",
        is_active=is_active,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


# =========================================================================
# 1. Environment Creation Tests
# =========================================================================


@pytest.mark.asyncio
async def test_create_environment_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify successful environment creation with proper server-assigned fields."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={
            "name": "Production",
            "slug": "production",
            "description": "Primary production runtime environment",
        },
        headers=_auth_header(owner),
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Production"
    assert data["slug"] == "production"
    assert data["description"] == "Primary production runtime environment"
    assert data["organization_id"] == str(org.id)
    assert data["project_id"] == str(project.id)
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_environment_missing_name_or_slug(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify 422 when required fields are missing."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    # Missing name
    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"slug": "production"},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 422

    # Missing slug
    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Production"},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 422


@pytest.mark.asyncio
async def test_create_environment_blank_name_rejected(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify whitespace-only or empty environment name is rejected with 422."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    for blank_name in ["", "   ", "\t\n"]:
        res = await client.post(
            f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
            json={"name": blank_name, "slug": "production"},
            headers=_auth_header(owner),
        )
        assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_environment_invalid_slug_rejected(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify slug regex rejects invalid formats."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    invalid_slugs = [
        "my_environment",
        "my environment",
        "-production",
        "production-",
        "UPPERCASE",
        "bad--slug",
        "slug with spaces",
        "prod!",
    ]
    for bad_slug in invalid_slugs:
        res = await client.post(
            f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
            json={"name": "Production", "slug": bad_slug},
            headers=_auth_header(owner),
        )
        assert res.status_code == 422, f"Expected 422 for slug '{bad_slug}'"


@pytest.mark.asyncio
async def test_create_environment_extra_fields_forbidden(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that clients cannot provide organization_id, project_id, is_active, or id."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    # Attempt to pass organization_id
    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={
            "name": "Env",
            "slug": "env-slug",
            "organization_id": str(uuid.uuid4()),
        },
        headers=_auth_header(owner),
    )
    assert res1.status_code == 422

    # Attempt to pass project_id
    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={
            "name": "Env",
            "slug": "env-slug",
            "project_id": str(uuid.uuid4()),
        },
        headers=_auth_header(owner),
    )
    assert res2.status_code == 422

    # Attempt to pass is_active
    res3 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={
            "name": "Env",
            "slug": "env-slug",
            "is_active": False,
        },
        headers=_auth_header(owner),
    )
    assert res3.status_code == 422

    # Attempt to pass id
    res4 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={
            "name": "Env",
            "slug": "env-slug",
            "id": str(uuid.uuid4()),
        },
        headers=_auth_header(owner),
    )
    assert res4.status_code == 422


@pytest.mark.asyncio
async def test_create_environment_duplicate_slug_conflict(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify duplicate slug within same project returns 409 Conflict."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Staging 1", "slug": "staging"},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 201

    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Staging 2", "slug": "staging"},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "ENVIRONMENT_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_same_slug_different_projects_allowed(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify identical environment slug across different projects is allowed."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project1 = await _create_project(test_db_session, org, slug="proj-one")
    project2 = await _create_project(test_db_session, org, slug="proj-two")
    await test_db_session.commit()

    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project1.id}/environments",
        json={"name": "Production", "slug": "production"},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 201

    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project2.id}/environments",
        json={"name": "Production", "slug": "production"},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 201
    assert res1.json()["id"] != res2.json()["id"]
    assert res1.json()["project_id"] != res2.json()["project_id"]


@pytest.mark.asyncio
async def test_create_environment_inactive_parent_project_rejected(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify creating an environment in an inactive parent project returns 400 PROJECT_INACTIVE."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org, is_active=False)
    await test_db_session.commit()

    res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Dev", "slug": "dev"},
        headers=_auth_header(owner),
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "PROJECT_INACTIVE"


@pytest.mark.asyncio
async def test_create_environment_cross_tenant_creation_attack(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify POST /orgs/A/projects/{Project-B}/environments fails with 404 (Project B not in Org A)."""
    user_a = await _create_user(test_db_session, "user_a@test.internal")
    user_b = await _create_user(test_db_session, "user_b@test.internal")
    org_a = await _create_org(test_db_session, slug="org-a")
    org_b = await _create_org(test_db_session, slug="org-b")
    await _add_member(test_db_session, org_a, user_a, OrgRole.OWNER)
    await _add_member(test_db_session, org_b, user_b, OrgRole.OWNER)
    project_b = await _create_project(test_db_session, org_b, slug="proj-b")
    await test_db_session.commit()

    # User A attempts to create an environment under Project B using Org A URL
    res = await client.post(
        f"/api/v1/organizations/{org_a.id}/projects/{project_b.id}/environments",
        json={"name": "Injected Env", "slug": "injected-env"},
        headers=_auth_header(user_a),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "PROJECT_NOT_FOUND"


# =========================================================================
# 2. List Environments Tests
# =========================================================================


@pytest.mark.asyncio
async def test_list_environments_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify listing environments returns deterministically ordered items."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.MEMBER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    # Create 3 environments
    slugs = ["development", "staging", "production"]
    for slug in slugs:
        res = await client.post(
            f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
            json={"name": slug.title(), "slug": slug},
            headers=_auth_header(user),
        )
        assert res.status_code == 201

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 3
    assert [d["slug"] for d in data] == slugs


@pytest.mark.asyncio
async def test_list_environments_excludes_other_projects_and_orgs(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify list only returns environments belonging to the specific project."""
    user = await _create_user(test_db_session)
    org_a = await _create_org(test_db_session, slug="org-a")
    org_b = await _create_org(test_db_session, slug="org-b")
    await _add_member(test_db_session, org_a, user, OrgRole.OWNER)
    await _add_member(test_db_session, org_b, user, OrgRole.OWNER)

    proj_a1 = await _create_project(test_db_session, org_a, slug="proj-a1")
    proj_a2 = await _create_project(test_db_session, org_a, slug="proj-a2")
    proj_b1 = await _create_project(test_db_session, org_b, slug="proj-b1")
    await test_db_session.commit()

    # Create envs in proj_a1, proj_a2, proj_b1
    await client.post(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_a1.id}/environments",
        json={"name": "Env A1", "slug": "env-a1"},
        headers=_auth_header(user),
    )
    await client.post(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_a2.id}/environments",
        json={"name": "Env A2", "slug": "env-a2"},
        headers=_auth_header(user),
    )
    await client.post(
        f"/api/v1/organizations/{org_b.id}/projects/{proj_b1.id}/environments",
        json={"name": "Env B1", "slug": "env-b1"},
        headers=_auth_header(user),
    )

    # Query proj_a1
    res = await client.get(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_a1.id}/environments",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["slug"] == "env-a1"
    assert data[0]["project_id"] == str(proj_a1.id)


@pytest.mark.asyncio
async def test_list_environments_empty_project(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify empty project returns empty list."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.MEMBER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_list_environments_inactive_parent_project_visible(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify existing environments under an inactive parent project remain visible."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    # Create environment while project is active
    create_res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Historical Env", "slug": "historical-env"},
        headers=_auth_header(user),
    )
    assert create_res.status_code == 201

    # Deactivate project
    del_res = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}",
        headers=_auth_header(user),
    )
    assert del_res.status_code == 200

    # List environments should still return the existing environment
    list_res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        headers=_auth_header(user),
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["slug"] == "historical-env"


# =========================================================================
# 3. Get Environment Tests & IDOR / Wrong-Project Protection
# =========================================================================


@pytest.mark.asyncio
async def test_get_environment_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify retrieving environment details by ID within project."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.VIEWER)
    project = await _create_project(test_db_session, org)

    env = Environment(
        organization_id=org.id,
        project_id=project.id,
        name="Staging",
        slug="staging",
        description="Staging cluster",
        is_active=True,
    )
    test_db_session.add(env)
    await test_db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(env.id)
    assert data["name"] == "Staging"
    assert data["slug"] == "staging"
    assert data["description"] == "Staging cluster"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_get_nonexistent_environment_returns_404(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify non-existent environment returns 404 ENVIRONMENT_NOT_FOUND."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.VIEWER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{uuid.uuid4()}",
        headers=_auth_header(user),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_wrong_project_same_org_protection(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify same-organization wrong-project access returns 404 for GET, PATCH, and DELETE."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)

    proj_a = await _create_project(test_db_session, org, slug="proj-a")
    proj_b = await _create_project(test_db_session, org, slug="proj-b")

    env_a = Environment(
        organization_id=org.id,
        project_id=proj_a.id,
        name="Env A",
        slug="env-a",
        is_active=True,
    )
    test_db_session.add(env_a)
    await test_db_session.commit()

    # 1. GET via Project B URL -> 404
    res_get = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{proj_b.id}/environments/{env_a.id}",
        headers=_auth_header(user),
    )
    assert res_get.status_code == 404
    assert res_get.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"

    # 2. PATCH via Project B URL -> 404
    res_patch = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{proj_b.id}/environments/{env_a.id}",
        json={"name": "Hacked Env"},
        headers=_auth_header(user),
    )
    assert res_patch.status_code == 404
    assert res_patch.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"

    # 3. DELETE via Project B URL -> 404
    res_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{proj_b.id}/environments/{env_a.id}",
        headers=_auth_header(user),
    )
    assert res_del.status_code == 404
    assert res_del.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_idor_cross_tenant_environment_access_blocked(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Explicit cross-tenant IDOR: User in Org A cannot GET, PATCH, or DELETE Environment in Org B."""
    user_a = await _create_user(test_db_session, "user_a@test.internal")
    user_b = await _create_user(test_db_session, "user_b@test.internal")
    org_a = await _create_org(test_db_session, slug="org-alpha")
    org_b = await _create_org(test_db_session, slug="org-beta")
    await _add_member(test_db_session, org_a, user_a, OrgRole.OWNER)
    await _add_member(test_db_session, org_b, user_b, OrgRole.OWNER)

    proj_a = await _create_project(test_db_session, org_a, slug="proj-a")
    proj_b = await _create_project(test_db_session, org_b, slug="proj-b")

    env_b = Environment(
        organization_id=org_b.id,
        project_id=proj_b.id,
        name="Env B",
        slug="env-b",
        is_active=True,
    )
    test_db_session.add(env_b)
    await test_db_session.commit()

    # 1. User A tries to GET Environment B using Org A and Project A URL -> 404
    res_get_a = await client.get(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_a.id}/environments/{env_b.id}",
        headers=_auth_header(user_a),
    )
    assert res_get_a.status_code == 404
    assert res_get_a.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"

    # 2. User A tries to PATCH Environment B using Org A and Project A URL -> 404
    res_patch_a = await client.patch(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_a.id}/environments/{env_b.id}",
        json={"name": "Hacked Name"},
        headers=_auth_header(user_a),
    )
    assert res_patch_a.status_code == 404
    assert res_patch_a.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"

    # 3. User A tries to DELETE Environment B using Org A and Project A URL -> 404
    res_del_a = await client.delete(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_a.id}/environments/{env_b.id}",
        headers=_auth_header(user_a),
    )
    assert res_del_a.status_code == 404
    assert res_del_a.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"

    # 4. User A tries to access Environment B directly using Org B URL -> 404 (non-member of Org B)
    res_get_b = await client.get(
        f"/api/v1/organizations/{org_b.id}/projects/{proj_b.id}/environments/{env_b.id}",
        headers=_auth_header(user_a),
    )
    assert res_get_b.status_code == 404
    assert res_get_b.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"


# =========================================================================
# 4. Update Environment Tests
# =========================================================================


@pytest.mark.asyncio
async def test_update_environment_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify updating name, slug, description, and empty update body."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.ADMIN)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    create_res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Original Name", "slug": "orig-slug", "description": "Original desc"},
        headers=_auth_header(user),
    )
    env_id = create_res.json()["id"]

    # 1. Update name only
    res1 = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_id}",
        json={"name": "Updated Name"},
        headers=_auth_header(user),
    )
    assert res1.status_code == 200
    assert res1.json()["name"] == "Updated Name"
    assert res1.json()["slug"] == "orig-slug"
    assert res1.json()["description"] == "Original desc"

    # 2. Update slug and description
    res2 = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_id}",
        json={"slug": "new-slug", "description": "New description"},
        headers=_auth_header(user),
    )
    assert res2.status_code == 200
    assert res2.json()["slug"] == "new-slug"
    assert res2.json()["description"] == "New description"

    # 3. Empty update body returns environment without errors
    res3 = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_id}",
        json={},
        headers=_auth_header(user),
    )
    assert res3.status_code == 200
    assert res3.json()["slug"] == "new-slug"


@pytest.mark.asyncio
async def test_update_environment_duplicate_slug_conflict(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify renaming an environment to an existing slug in the same project returns 409."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Dev", "slug": "dev"},
        headers=_auth_header(user),
    )
    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Staging", "slug": "staging"},
        headers=_auth_header(user),
    )
    staging_id = res2.json()["id"]

    # Attempt to change Staging's slug to Dev's slug
    res_conflict = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{staging_id}",
        json={"slug": "dev"},
        headers=_auth_header(user),
    )
    assert res_conflict.status_code == 409
    assert res_conflict.json()["error"]["code"] == "ENVIRONMENT_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_update_environment_same_slug_different_project_allowed(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify updating slug to match an environment in a DIFFERENT project is allowed."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    proj1 = await _create_project(test_db_session, org, slug="proj-1")
    proj2 = await _create_project(test_db_session, org, slug="proj-2")
    await test_db_session.commit()

    # Create "prod" in proj1
    await client.post(
        f"/api/v1/organizations/{org.id}/projects/{proj1.id}/environments",
        json={"name": "Production", "slug": "prod"},
        headers=_auth_header(user),
    )

    # Create "staging" in proj2
    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{proj2.id}/environments",
        json={"name": "Staging", "slug": "staging"},
        headers=_auth_header(user),
    )
    proj2_env_id = res2.json()["id"]

    # Rename proj2's env to "prod" (allowed because it's in a different project)
    res_update = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{proj2.id}/environments/{proj2_env_id}",
        json={"slug": "prod"},
        headers=_auth_header(user),
    )
    assert res_update.status_code == 200
    assert res_update.json()["slug"] == "prod"


@pytest.mark.asyncio
async def test_update_inactive_environment_rejected(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify updates to deactivated environments return 400 ENVIRONMENT_INACTIVE."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Active Env", "slug": "active-env"},
        headers=_auth_header(user),
    )
    env_id = res.json()["id"]

    # Deactivate
    del_res = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_id}",
        headers=_auth_header(user),
    )
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False

    # Attempt to update inactive environment
    patch_res = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_id}",
        json={"name": "New Name"},
        headers=_auth_header(user),
    )
    assert patch_res.status_code == 400
    assert patch_res.json()["error"]["code"] == "ENVIRONMENT_INACTIVE"


@pytest.mark.asyncio
async def test_update_environment_forbidden_fields(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that clients cannot alter project_id, organization_id, id, or is_active via PATCH."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Env", "slug": "env"},
        headers=_auth_header(user),
    )
    env_id = res.json()["id"]

    for forbidden_payload in [
        {"project_id": str(uuid.uuid4())},
        {"organization_id": str(uuid.uuid4())},
        {"id": str(uuid.uuid4())},
        {"is_active": True},
    ]:
        patch_res = await client.patch(
            f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_id}",
            json=forbidden_payload,
            headers=_auth_header(user),
        )
        assert patch_res.status_code == 422


# =========================================================================
# 5. Delete (Soft Deactivation) Tests
# =========================================================================


@pytest.mark.asyncio
async def test_delete_environment_soft_deactivation(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify DELETE performs soft-deactivation (is_active=False) preserving DB row."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    create_res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "To Delete", "slug": "to-delete"},
        headers=_auth_header(owner),
    )
    env_id = uuid.UUID(create_res.json()["id"])

    del_res = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_id}",
        headers=_auth_header(owner),
    )
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False

    # Verify row still exists in DB with is_active=False
    db_env = await test_db_session.scalar(select(Environment).where(Environment.id == env_id))
    assert db_env is not None
    assert db_env.is_active is False


@pytest.mark.asyncio
async def test_delete_environment_idempotent(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify repeated DELETE calls are idempotent and return 200 with is_active=False."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    create_res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Repeat Delete", "slug": "repeat-delete"},
        headers=_auth_header(owner),
    )
    env_id = create_res.json()["id"]

    # First delete
    res1 = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_id}",
        headers=_auth_header(owner),
    )
    assert res1.status_code == 200
    assert res1.json()["is_active"] is False

    # Second delete
    res2 = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_id}",
        headers=_auth_header(owner),
    )
    assert res2.status_code == 200
    assert res2.json()["is_active"] is False


# =========================================================================
# 6. Role Matrix Authorization Tests
# =========================================================================


@pytest.mark.asyncio
async def test_environment_role_matrix(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify RBAC permissions across roles:

    - OWNER: read/create/update/delete allowed
    - ADMIN: read/create/update/delete allowed
    - MEMBER: read/create/update allowed, delete denied (403)
    - VIEWER: read allowed, create/update/delete denied (403)
    """
    owner = await _create_user(test_db_session, "owner@test.internal")
    admin = await _create_user(test_db_session, "admin@test.internal")
    member = await _create_user(test_db_session, "member@test.internal")
    viewer = await _create_user(test_db_session, "viewer@test.internal")

    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    await _add_member(test_db_session, org, admin, OrgRole.ADMIN)
    await _add_member(test_db_session, org, member, OrgRole.MEMBER)
    await _add_member(test_db_session, org, viewer, OrgRole.VIEWER)

    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    # --- VIEWER ---
    # VIEWER cannot create -> 403
    res_v_create = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "V Env", "slug": "v-env"},
        headers=_auth_header(viewer),
    )
    assert res_v_create.status_code == 403

    # --- MEMBER ---
    # MEMBER can create -> 201
    res_m_create = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "M Env", "slug": "m-env"},
        headers=_auth_header(member),
    )
    assert res_m_create.status_code == 201
    m_env_id = res_m_create.json()["id"]

    # VIEWER can read -> 200
    res_v_get = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{m_env_id}",
        headers=_auth_header(viewer),
    )
    assert res_v_get.status_code == 200

    # VIEWER cannot update -> 403
    res_v_patch = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{m_env_id}",
        json={"name": "Hacked"},
        headers=_auth_header(viewer),
    )
    assert res_v_patch.status_code == 403

    # MEMBER can update -> 200
    res_m_patch = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{m_env_id}",
        json={"name": "M Env Updated"},
        headers=_auth_header(member),
    )
    assert res_m_patch.status_code == 200

    # VIEWER cannot delete -> 403
    res_v_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{m_env_id}",
        headers=_auth_header(viewer),
    )
    assert res_v_del.status_code == 403

    # MEMBER cannot delete -> 403
    res_m_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{m_env_id}",
        headers=_auth_header(member),
    )
    assert res_m_del.status_code == 403

    # --- ADMIN ---
    # ADMIN can create and delete -> 201 & 200
    res_a_create = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "A Env", "slug": "a-env"},
        headers=_auth_header(admin),
    )
    assert res_a_create.status_code == 201
    a_env_id = res_a_create.json()["id"]

    res_a_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{a_env_id}",
        headers=_auth_header(admin),
    )
    assert res_a_del.status_code == 200
    assert res_a_del.json()["is_active"] is False

    # --- OWNER ---
    # OWNER can delete -> 200
    res_o_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{m_env_id}",
        headers=_auth_header(owner),
    )
    assert res_o_del.status_code == 200
    assert res_o_del.json()["is_active"] is False


# =========================================================================
# 7. Inactive Organization & Unauthenticated / Unverified Access
# =========================================================================


@pytest.mark.asyncio
async def test_environment_operations_on_inactive_organization_forbidden(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify operations on an inactive organization return 403 ORGANIZATION_INACTIVE."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session, is_active=False)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    # Create environment against inactive org -> 403
    res_create = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        json={"name": "Env", "slug": "env"},
        headers=_auth_header(user),
    )
    assert res_create.status_code == 403
    assert res_create.json()["error"]["code"] == "ORGANIZATION_INACTIVE"

    # List environments against inactive org -> 403
    res_list = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        headers=_auth_header(user),
    )
    assert res_list.status_code == 403
    assert res_list.json()["error"]["code"] == "ORGANIZATION_INACTIVE"


@pytest.mark.asyncio
async def test_environment_endpoints_unauthenticated_and_unverified(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify unauthenticated requests return 401 and unverified users return 403."""
    org = await _create_org(test_db_session)
    unverified_user = await _create_user(test_db_session, is_verified=False)
    await _add_member(test_db_session, org, unverified_user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    await test_db_session.commit()

    # 1. Unauthenticated -> 401
    res_unauth = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments"
    )
    assert res_unauth.status_code == 401

    # 2. Unverified user -> 403 FORBIDDEN
    res_unver = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments",
        headers=_auth_header(unverified_user),
    )
    assert res_unver.status_code == 403
