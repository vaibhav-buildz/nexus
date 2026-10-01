"""Integration tests for Service CRUD API endpoints, 4-level hierarchy validation, tenant isolation, and RBAC authorization."""

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
from app.models.service import Service, ServiceType
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


async def _create_environment(
    db: AsyncSession,
    project: Project,
    slug: str | None = None,
    is_active: bool = True,
) -> Environment:
    env = Environment(
        organization_id=project.organization_id,
        project_id=project.id,
        name="Test Environment",
        slug=slug or f"env-{uuid.uuid4().hex[:8]}",
        description="Environment description",
        is_active=is_active,
    )
    db.add(env)
    await db.flush()
    await db.refresh(env)
    return env


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


# =========================================================================
# 1. Service Creation Tests
# =========================================================================


@pytest.mark.asyncio
async def test_create_service_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify successful service creation with server-assigned fields and hierarchy scoping."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services",
        json={
            "name": "Auth Service",
            "slug": "auth-service",
            "description": "Authentication and identity workload",
            "service_type": "APPLICATION",
        },
        headers=_auth_header(owner),
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Auth Service"
    assert data["slug"] == "auth-service"
    assert data["description"] == "Authentication and identity workload"
    assert data["service_type"] == "APPLICATION"
    assert data["organization_id"] == str(org.id)
    assert data["project_id"] == str(project.id)
    assert data["environment_id"] == str(env.id)
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_service_validation_errors(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify 422 for missing required fields, blank name, invalid slug, or invalid service_type."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    # Missing name
    res1 = await client.post(
        base_url,
        json={"slug": "svc", "service_type": "APPLICATION"},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 422

    # Missing slug
    res2 = await client.post(
        base_url,
        json={"name": "Svc", "service_type": "APPLICATION"},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 422

    # Missing service_type
    res3 = await client.post(
        base_url,
        json={"name": "Svc", "slug": "svc"},
        headers=_auth_header(owner),
    )
    assert res3.status_code == 422

    # Blank / whitespace-only name
    for blank_name in ["", "   ", "\t\n"]:
        res_blank = await client.post(
            base_url,
            json={"name": blank_name, "slug": "svc", "service_type": "APPLICATION"},
            headers=_auth_header(owner),
        )
        assert res_blank.status_code == 422

    # Invalid slug formats
    for bad_slug in ["my_service", "my service", "-service", "service-", "UPPERCASE", "bad--slug", "svc!"]:
        res_slug = await client.post(
            base_url,
            json={"name": "Svc", "slug": bad_slug, "service_type": "APPLICATION"},
            headers=_auth_header(owner),
        )
        assert res_slug.status_code == 422

    # Invalid service_type
    for bad_type in ["MICROSERVICE", "LAMBDA", "INVALID", "application"]:
        res_type = await client.post(
            base_url,
            json={"name": "Svc", "slug": "svc", "service_type": bad_type},
            headers=_auth_header(owner),
        )
        assert res_type.status_code == 422


@pytest.mark.asyncio
async def test_create_service_field_lengths_and_extra_fields(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify max length constraints and rejection of extra / forbidden fields."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    # Name > 128 chars
    res_name = await client.post(
        base_url,
        json={"name": "x" * 129, "slug": "svc", "service_type": "APPLICATION"},
        headers=_auth_header(owner),
    )
    assert res_name.status_code == 422

    # Slug > 64 chars
    res_slug = await client.post(
        base_url,
        json={"name": "Svc", "slug": "x" * 65, "service_type": "APPLICATION"},
        headers=_auth_header(owner),
    )
    assert res_slug.status_code == 422

    # Description > 500 chars
    res_desc = await client.post(
        base_url,
        json={"name": "Svc", "slug": "svc", "service_type": "APPLICATION", "description": "d" * 501},
        headers=_auth_header(owner),
    )
    assert res_desc.status_code == 422

    # Injected forbidden fields
    for field_name in ["id", "organization_id", "project_id", "environment_id", "is_active", "created_at"]:
        res_extra = await client.post(
            base_url,
            json={"name": "Svc", "slug": "svc", "service_type": "APPLICATION", field_name: "injected"},
            headers=_auth_header(owner),
        )
        assert res_extra.status_code == 422


@pytest.mark.asyncio
async def test_create_service_duplicate_slug_conflict(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify duplicate slug within same environment returns 409 Conflict."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    res1 = await client.post(
        base_url,
        json={"name": "Worker A", "slug": "queue-worker", "service_type": "WORKER"},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 201

    res2 = await client.post(
        base_url,
        json={"name": "Worker B", "slug": "queue-worker", "service_type": "WORKER"},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "SERVICE_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_same_service_slug_different_environments_allowed(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify identical service slug across different environments is allowed."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env_staging = await _create_environment(test_db_session, project, slug="staging")
    env_prod = await _create_environment(test_db_session, project, slug="production")
    await test_db_session.commit()

    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_staging.id}/services",
        json={"name": "API Service", "slug": "api-service", "service_type": "APPLICATION"},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 201

    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_prod.id}/services",
        json={"name": "API Service", "slug": "api-service", "service_type": "APPLICATION"},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 201
    assert res1.json()["id"] != res2.json()["id"]
    assert res1.json()["environment_id"] != res2.json()["environment_id"]


@pytest.mark.asyncio
async def test_create_service_inactive_parent_environment_rejected(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify creating a service in an inactive parent environment returns 400 ENVIRONMENT_INACTIVE."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project, is_active=False)
    await test_db_session.commit()

    res = await client.post(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services",
        json={"name": "Svc", "slug": "svc", "service_type": "APPLICATION"},
        headers=_auth_header(owner),
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "ENVIRONMENT_INACTIVE"


@pytest.mark.asyncio
async def test_create_service_cross_tenant_creation_attack(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify cross-tenant creation attempt fails with 404 (non-disclosure)."""
    user_a = await _create_user(test_db_session, "user_a@test.internal")
    user_b = await _create_user(test_db_session, "user_b@test.internal")
    org_a = await _create_org(test_db_session, slug="org-a")
    org_b = await _create_org(test_db_session, slug="org-b")
    await _add_member(test_db_session, org_a, user_a, OrgRole.OWNER)
    await _add_member(test_db_session, org_b, user_b, OrgRole.OWNER)
    proj_b = await _create_project(test_db_session, org_b, slug="proj-b")
    env_b = await _create_environment(test_db_session, proj_b, slug="env-b")
    await test_db_session.commit()

    # User A tries to create service using Org A URL with Org B's project & environment
    res = await client.post(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_b.id}/environments/{env_b.id}/services",
        json={"name": "Attack Svc", "slug": "attack-svc", "service_type": "APPLICATION"},
        headers=_auth_header(user_a),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "PROJECT_NOT_FOUND"


# =========================================================================
# 2. List Services Tests
# =========================================================================


@pytest.mark.asyncio
async def test_list_services_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify listing services returns deterministically ordered items in requested environment."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.MEMBER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    slugs = ["web-app", "cache-cluster", "bg-worker"]
    types = ["APPLICATION", "CACHE", "WORKER"]
    for slug, stype in zip(slugs, types):
        res = await client.post(
            f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services",
            json={"name": slug.title(), "slug": slug, "service_type": stype},
            headers=_auth_header(user),
        )
        assert res.status_code == 201

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 3
    assert [d["slug"] for d in data] == slugs


@pytest.mark.asyncio
async def test_list_services_excludes_other_environments_and_projects(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify list only returns services belonging strictly to the requested environment."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    proj1 = await _create_project(test_db_session, org, slug="proj-1")
    env1 = await _create_environment(test_db_session, proj1, slug="env-1")
    env2 = await _create_environment(test_db_session, proj1, slug="env-2")
    await test_db_session.commit()

    # Create service in env1
    await client.post(
        f"/api/v1/organizations/{org.id}/projects/{proj1.id}/environments/{env1.id}/services",
        json={"name": "Svc 1", "slug": "svc-1", "service_type": "APPLICATION"},
        headers=_auth_header(user),
    )
    # Create service in env2
    await client.post(
        f"/api/v1/organizations/{org.id}/projects/{proj1.id}/environments/{env2.id}/services",
        json={"name": "Svc 2", "slug": "svc-2", "service_type": "APPLICATION"},
        headers=_auth_header(user),
    )

    # Query env1
    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{proj1.id}/environments/{env1.id}/services",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["slug"] == "svc-1"
    assert data[0]["environment_id"] == str(env1.id)


@pytest.mark.asyncio
async def test_list_services_empty_environment(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify empty environment returns empty list."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.MEMBER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    assert res.json() == []


# =========================================================================
# 3. Get Service Tests & Hierarchy / IDOR Protection
# =========================================================================


@pytest.mark.asyncio
async def test_get_service_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify retrieving service details by ID within environment."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.VIEWER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)

    service = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env.id,
        name="Redis Cache",
        slug="redis-cache",
        description="Session store",
        service_type="CACHE",
        is_active=True,
    )
    test_db_session.add(service)
    await test_db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services/{service.id}",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(service.id)
    assert data["name"] == "Redis Cache"
    assert data["slug"] == "redis-cache"
    assert data["description"] == "Session store"
    assert data["service_type"] == "CACHE"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_get_nonexistent_service_returns_404(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify non-existent service returns 404 SERVICE_NOT_FOUND."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.VIEWER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services/{uuid.uuid4()}",
        headers=_auth_header(user),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "SERVICE_NOT_FOUND"


@pytest.mark.asyncio
async def test_wrong_environment_same_project_protection(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify accessing a service using another environment's URL within same project returns 404."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env_a = await _create_environment(test_db_session, project, slug="env-a")
    env_b = await _create_environment(test_db_session, project, slug="env-b")

    svc_a = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env_a.id,
        name="Svc A",
        slug="svc-a",
        service_type="APPLICATION",
        is_active=True,
    )
    test_db_session.add(svc_a)
    await test_db_session.commit()

    # 1. GET via Env B URL -> 404
    res_get = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_b.id}/services/{svc_a.id}",
        headers=_auth_header(user),
    )
    assert res_get.status_code == 404
    assert res_get.json()["error"]["code"] == "SERVICE_NOT_FOUND"

    # 2. PATCH via Env B URL -> 404
    res_patch = await client.patch(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_b.id}/services/{svc_a.id}",
        json={"name": "Hacked"},
        headers=_auth_header(user),
    )
    assert res_patch.status_code == 404
    assert res_patch.json()["error"]["code"] == "SERVICE_NOT_FOUND"

    # 3. DELETE via Env B URL -> 404
    res_del = await client.delete(
        f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env_b.id}/services/{svc_a.id}",
        headers=_auth_header(user),
    )
    assert res_del.status_code == 404
    assert res_del.json()["error"]["code"] == "SERVICE_NOT_FOUND"


@pytest.mark.asyncio
async def test_wrong_project_same_org_protection_for_service(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify accessing a service using a wrong project ID returns 404."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    proj_a = await _create_project(test_db_session, org, slug="proj-a")
    proj_b = await _create_project(test_db_session, org, slug="proj-b")
    env_a = await _create_environment(test_db_session, proj_a, slug="env-a")

    svc_a = Service(
        organization_id=org.id,
        project_id=proj_a.id,
        environment_id=env_a.id,
        name="Svc A",
        slug="svc-a",
        service_type="APPLICATION",
        is_active=True,
    )
    test_db_session.add(svc_a)
    await test_db_session.commit()

    # Access using Proj B in URL
    res = await client.get(
        f"/api/v1/organizations/{org.id}/projects/{proj_b.id}/environments/{env_a.id}/services/{svc_a.id}",
        headers=_auth_header(user),
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_idor_cross_tenant_service_access_blocked(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Explicit cross-tenant IDOR: User in Org A cannot access Service in Org B."""
    user_a = await _create_user(test_db_session, "user_a@test.internal")
    user_b = await _create_user(test_db_session, "user_b@test.internal")
    org_a = await _create_org(test_db_session, slug="org-alpha")
    org_b = await _create_org(test_db_session, slug="org-beta")
    await _add_member(test_db_session, org_a, user_a, OrgRole.OWNER)
    await _add_member(test_db_session, org_b, user_b, OrgRole.OWNER)

    proj_a = await _create_project(test_db_session, org_a, slug="proj-a")
    env_a = await _create_environment(test_db_session, proj_a, slug="env-a")

    proj_b = await _create_project(test_db_session, org_b, slug="proj-b")
    env_b = await _create_environment(test_db_session, proj_b, slug="env-b")

    svc_b = Service(
        organization_id=org_b.id,
        project_id=proj_b.id,
        environment_id=env_b.id,
        name="Svc B",
        slug="svc-b",
        service_type="APPLICATION",
        is_active=True,
    )
    test_db_session.add(svc_b)
    await test_db_session.commit()

    # User A tries to GET Service B using Org A URL -> 404
    res_get_a = await client.get(
        f"/api/v1/organizations/{org_a.id}/projects/{proj_a.id}/environments/{env_a.id}/services/{svc_b.id}",
        headers=_auth_header(user_a),
    )
    assert res_get_a.status_code == 404
    assert res_get_a.json()["error"]["code"] == "SERVICE_NOT_FOUND"

    # User A tries to access directly using Org B URL -> 404 (non-member)
    res_get_b = await client.get(
        f"/api/v1/organizations/{org_b.id}/projects/{proj_b.id}/environments/{env_b.id}/services/{svc_b.id}",
        headers=_auth_header(user_a),
    )
    assert res_get_b.status_code == 404
    assert res_get_b.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"


# =========================================================================
# 4. Update Service Tests
# =========================================================================


@pytest.mark.asyncio
async def test_update_service_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify updating name, slug, description, service_type, and empty update payload."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.ADMIN)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    create_res = await client.post(
        base_url,
        json={"name": "Original Name", "slug": "orig-slug", "description": "Original desc", "service_type": "APPLICATION"},
        headers=_auth_header(user),
    )
    svc_id = create_res.json()["id"]

    # 1. Update name and service_type
    res1 = await client.patch(
        f"{base_url}/{svc_id}",
        json={"name": "New Name", "service_type": "WORKER"},
        headers=_auth_header(user),
    )
    assert res1.status_code == 200
    assert res1.json()["name"] == "New Name"
    assert res1.json()["service_type"] == "WORKER"
    assert res1.json()["slug"] == "orig-slug"

    # 2. Update slug and description
    res2 = await client.patch(
        f"{base_url}/{svc_id}",
        json={"slug": "new-slug", "description": "Updated desc"},
        headers=_auth_header(user),
    )
    assert res2.status_code == 200
    assert res2.json()["slug"] == "new-slug"
    assert res2.json()["description"] == "Updated desc"

    # 3. Empty update body returns current service without error
    res3 = await client.patch(
        f"{base_url}/{svc_id}",
        json={},
        headers=_auth_header(user),
    )
    assert res3.status_code == 200
    assert res3.json()["slug"] == "new-slug"


@pytest.mark.asyncio
async def test_update_service_duplicate_slug_conflict(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify renaming a service to an existing slug in same environment returns 409."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    await client.post(
        base_url,
        json={"name": "Svc 1", "slug": "svc-one", "service_type": "APPLICATION"},
        headers=_auth_header(user),
    )
    res2 = await client.post(
        base_url,
        json={"name": "Svc 2", "slug": "svc-two", "service_type": "APPLICATION"},
        headers=_auth_header(user),
    )
    svc2_id = res2.json()["id"]

    # Attempt to change svc2's slug to svc1's slug
    res_conflict = await client.patch(
        f"{base_url}/{svc2_id}",
        json={"slug": "svc-one"},
        headers=_auth_header(user),
    )
    assert res_conflict.status_code == 409
    assert res_conflict.json()["error"]["code"] == "SERVICE_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_update_inactive_service_rejected(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify updates to deactivated services return 400 SERVICE_INACTIVE."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    res = await client.post(
        base_url,
        json={"name": "Active Svc", "slug": "active-svc", "service_type": "APPLICATION"},
        headers=_auth_header(user),
    )
    svc_id = res.json()["id"]

    # Soft delete (deactivate)
    del_res = await client.delete(
        f"{base_url}/{svc_id}",
        headers=_auth_header(user),
    )
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False

    # Attempt to update
    patch_res = await client.patch(
        f"{base_url}/{svc_id}",
        json={"name": "New Name"},
        headers=_auth_header(user),
    )
    assert patch_res.status_code == 400
    assert patch_res.json()["error"]["code"] == "SERVICE_INACTIVE"


@pytest.mark.asyncio
async def test_update_service_forbidden_fields(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that clients cannot alter hierarchy IDs or is_active via PATCH."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    res = await client.post(
        base_url,
        json={"name": "Svc", "slug": "svc", "service_type": "APPLICATION"},
        headers=_auth_header(user),
    )
    svc_id = res.json()["id"]

    for forbidden_payload in [
        {"organization_id": str(uuid.uuid4())},
        {"project_id": str(uuid.uuid4())},
        {"environment_id": str(uuid.uuid4())},
        {"id": str(uuid.uuid4())},
        {"is_active": True},
    ]:
        patch_res = await client.patch(
            f"{base_url}/{svc_id}",
            json=forbidden_payload,
            headers=_auth_header(user),
        )
        assert patch_res.status_code == 422


# =========================================================================
# 5. Delete (Soft Deactivation) Tests
# =========================================================================


@pytest.mark.asyncio
async def test_delete_service_soft_deactivation(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify DELETE performs soft-deactivation (is_active=False) preserving DB row."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    create_res = await client.post(
        base_url,
        json={"name": "To Delete", "slug": "to-delete", "service_type": "DATABASE"},
        headers=_auth_header(owner),
    )
    svc_id = uuid.UUID(create_res.json()["id"])

    del_res = await client.delete(
        f"{base_url}/{svc_id}",
        headers=_auth_header(owner),
    )
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False

    # Verify row still exists in DB with is_active=False
    db_svc = await test_db_session.scalar(select(Service).where(Service.id == svc_id))
    assert db_svc is not None
    assert db_svc.is_active is False

    # Verify inactive service remains retrievable via GET
    get_res = await client.get(
        f"{base_url}/{svc_id}",
        headers=_auth_header(owner),
    )
    assert get_res.status_code == 200
    assert get_res.json()["is_active"] is False


@pytest.mark.asyncio
async def test_delete_service_idempotent(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify repeated DELETE calls are idempotent and return 200 with is_active=False."""
    owner = await _create_user(test_db_session)
    org = await _create_org(test_db_session)
    await _add_member(test_db_session, org, owner, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    create_res = await client.post(
        base_url,
        json={"name": "Repeat Delete", "slug": "repeat-delete", "service_type": "QUEUE"},
        headers=_auth_header(owner),
    )
    svc_id = create_res.json()["id"]

    res1 = await client.delete(f"{base_url}/{svc_id}", headers=_auth_header(owner))
    assert res1.status_code == 200
    assert res1.json()["is_active"] is False

    res2 = await client.delete(f"{base_url}/{svc_id}", headers=_auth_header(owner))
    assert res2.status_code == 200
    assert res2.json()["is_active"] is False


# =========================================================================
# 6. Role Matrix Authorization Tests
# =========================================================================


@pytest.mark.asyncio
async def test_service_role_matrix(
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
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    # --- VIEWER ---
    # VIEWER cannot create -> 403
    res_v_create = await client.post(
        base_url,
        json={"name": "V Svc", "slug": "v-svc", "service_type": "APPLICATION"},
        headers=_auth_header(viewer),
    )
    assert res_v_create.status_code == 403

    # --- MEMBER ---
    # MEMBER can create -> 201
    res_m_create = await client.post(
        base_url,
        json={"name": "M Svc", "slug": "m-svc", "service_type": "APPLICATION"},
        headers=_auth_header(member),
    )
    assert res_m_create.status_code == 201
    m_svc_id = res_m_create.json()["id"]

    # VIEWER can read -> 200
    res_v_get = await client.get(
        f"{base_url}/{m_svc_id}",
        headers=_auth_header(viewer),
    )
    assert res_v_get.status_code == 200

    # VIEWER cannot update -> 403
    res_v_patch = await client.patch(
        f"{base_url}/{m_svc_id}",
        json={"name": "Hacked"},
        headers=_auth_header(viewer),
    )
    assert res_v_patch.status_code == 403

    # MEMBER can update -> 200
    res_m_patch = await client.patch(
        f"{base_url}/{m_svc_id}",
        json={"name": "M Svc Updated"},
        headers=_auth_header(member),
    )
    assert res_m_patch.status_code == 200

    # VIEWER cannot delete -> 403
    res_v_del = await client.delete(
        f"{base_url}/{m_svc_id}",
        headers=_auth_header(viewer),
    )
    assert res_v_del.status_code == 403

    # MEMBER cannot delete -> 403
    res_m_del = await client.delete(
        f"{base_url}/{m_svc_id}",
        headers=_auth_header(member),
    )
    assert res_m_del.status_code == 403

    # --- ADMIN ---
    # ADMIN can create and delete -> 201 & 200
    res_a_create = await client.post(
        base_url,
        json={"name": "A Svc", "slug": "a-svc", "service_type": "WORKER"},
        headers=_auth_header(admin),
    )
    assert res_a_create.status_code == 201
    a_svc_id = res_a_create.json()["id"]

    res_a_del = await client.delete(
        f"{base_url}/{a_svc_id}",
        headers=_auth_header(admin),
    )
    assert res_a_del.status_code == 200
    assert res_a_del.json()["is_active"] is False

    # --- OWNER ---
    # OWNER can delete -> 200
    res_o_del = await client.delete(
        f"{base_url}/{m_svc_id}",
        headers=_auth_header(owner),
    )
    assert res_o_del.status_code == 200
    assert res_o_del.json()["is_active"] is False


# =========================================================================
# 7. Inactive Organization & Unauthenticated / Unverified Access
# =========================================================================


@pytest.mark.asyncio
async def test_service_operations_on_inactive_organization_forbidden(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify operations on an inactive organization return 403 ORGANIZATION_INACTIVE."""
    user = await _create_user(test_db_session)
    org = await _create_org(test_db_session, is_active=False)
    await _add_member(test_db_session, org, user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    # Create service against inactive org -> 403
    res_create = await client.post(
        base_url,
        json={"name": "Svc", "slug": "svc", "service_type": "APPLICATION"},
        headers=_auth_header(user),
    )
    assert res_create.status_code == 403
    assert res_create.json()["error"]["code"] == "ORGANIZATION_INACTIVE"

    # List services against inactive org -> 403
    res_list = await client.get(
        base_url,
        headers=_auth_header(user),
    )
    assert res_list.status_code == 403
    assert res_list.json()["error"]["code"] == "ORGANIZATION_INACTIVE"


@pytest.mark.asyncio
async def test_service_endpoints_unauthenticated_and_unverified(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify unauthenticated requests return 401 and unverified users return 403."""
    org = await _create_org(test_db_session)
    unverified_user = await _create_user(test_db_session, is_verified=False)
    await _add_member(test_db_session, org, unverified_user, OrgRole.OWNER)
    project = await _create_project(test_db_session, org)
    env = await _create_environment(test_db_session, project)
    await test_db_session.commit()

    base_url = f"/api/v1/organizations/{org.id}/projects/{project.id}/environments/{env.id}/services"

    # 1. Unauthenticated -> 401
    res_unauth = await client.get(base_url)
    assert res_unauth.status_code == 401

    # 2. Unverified user -> 403 FORBIDDEN
    res_unver = await client.get(base_url, headers=_auth_header(unverified_user))
    assert res_unver.status_code == 403
