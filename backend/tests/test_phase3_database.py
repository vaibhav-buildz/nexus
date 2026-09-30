"""Database-level integration tests for Phase 3 models: Project, Environment, and Service."""

from datetime import datetime, timezone
import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.environment import Environment
from app.models.organization import Organization
from app.models.project import Project
from app.models.service import Service, ServiceType


async def _create_test_organization(
    db: AsyncSession,
    name: str = "Acme Corp",
    slug: str | None = None,
) -> Organization:
    """Helper to create and persist an Organization for testing."""
    org = Organization(
        name=name,
        slug=slug or f"org-{uuid.uuid4().hex[:8]}",
        description="Test organization description",
        is_active=True,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def _create_test_project(
    db: AsyncSession,
    org: Organization,
    name: str = "Core Platform",
    slug: str = "core-platform",
) -> Project:
    """Helper to create and persist a Project for testing."""
    project = Project(
        organization_id=org.id,
        name=name,
        slug=slug,
        description="Core platform project description",
        is_active=True,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_test_environment(
    db: AsyncSession,
    project: Project,
    name: str = "Production",
    slug: str = "production",
) -> Environment:
    """Helper to create and persist an Environment for testing."""
    env = Environment(
        organization_id=project.organization_id,
        project_id=project.id,
        name=name,
        slug=slug,
        description="Production environment description",
        is_active=True,
    )
    db.add(env)
    await db.commit()
    await db.refresh(env)
    return env


# ==========================================
# 1. Project Tests
# ==========================================


@pytest.mark.asyncio
async def test_project_creation(test_db_session: AsyncSession) -> None:
    """Verify Project creation, default values, UUID primary key, and timestamps."""
    org = await _create_test_organization(test_db_session)
    project = Project(
        organization_id=org.id,
        name="Telemetry Pipeline",
        slug="telemetry-pipeline",
        description="Distributed telemetry collection service",
        is_active=True,
    )
    test_db_session.add(project)
    await test_db_session.commit()
    await test_db_session.refresh(project)

    assert isinstance(project.id, uuid.UUID)
    assert project.organization_id == org.id
    assert project.name == "Telemetry Pipeline"
    assert project.slug == "telemetry-pipeline"
    assert project.description == "Distributed telemetry collection service"
    assert project.is_active is True
    assert isinstance(project.created_at, datetime)
    assert isinstance(project.updated_at, datetime)


@pytest.mark.asyncio
async def test_project_organization_relationship(test_db_session: AsyncSession) -> None:
    """Verify bidirectional relationship between Organization and Project."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org, name="Edge Gateway", slug="edge-gateway")

    # Access via project
    assert project.organization is not None
    assert project.organization.id == org.id

    # Access via organization after refreshing parent
    await test_db_session.refresh(org)
    assert any(p.id == project.id for p in org.projects)


@pytest.mark.asyncio
async def test_project_duplicate_slug_same_organization_rejected(
    test_db_session: AsyncSession,
) -> None:
    """Verify that a duplicate project slug within the same organization is rejected."""
    org = await _create_test_organization(test_db_session)
    await _create_test_project(test_db_session, org, name="API", slug="api-svc")

    dup = Project(
        organization_id=org.id,
        name="Another API",
        slug="api-svc",
    )
    test_db_session.add(dup)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_project_same_slug_different_organizations_allowed(
    test_db_session: AsyncSession,
) -> None:
    """Verify that identical project slugs across different organizations are allowed."""
    org1 = await _create_test_organization(test_db_session, slug="tenant-alpha")
    org2 = await _create_test_organization(test_db_session, slug="tenant-beta")

    p1 = await _create_test_project(test_db_session, org1, name="API", slug="shared-slug")
    p2 = await _create_test_project(test_db_session, org2, name="API", slug="shared-slug")

    assert p1.slug == p2.slug == "shared-slug"
    assert p1.id != p2.id
    assert p1.organization_id != p2.organization_id


# ==========================================
# 2. Environment Tests
# ==========================================


@pytest.mark.asyncio
async def test_environment_creation(test_db_session: AsyncSession) -> None:
    """Verify Environment creation, field persistence, and timestamps."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org)

    env = Environment(
        organization_id=org.id,
        project_id=project.id,
        name="Staging",
        slug="staging",
        description="Pre-production staging environment",
        is_active=True,
    )
    test_db_session.add(env)
    await test_db_session.commit()
    await test_db_session.refresh(env)

    assert isinstance(env.id, uuid.UUID)
    assert env.organization_id == org.id
    assert env.project_id == project.id
    assert env.name == "Staging"
    assert env.slug == "staging"
    assert env.description == "Pre-production staging environment"
    assert env.is_active is True
    assert isinstance(env.created_at, datetime)
    assert isinstance(env.updated_at, datetime)


@pytest.mark.asyncio
async def test_environment_relationships(test_db_session: AsyncSession) -> None:
    """Verify bidirectional relationship between Project, Organization, and Environment."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org)
    env = await _create_test_environment(test_db_session, project, name="Dev", slug="dev")

    assert env.project.id == project.id
    assert env.organization.id == org.id

    await test_db_session.refresh(project)
    assert any(e.id == env.id for e in project.environments)


@pytest.mark.asyncio
async def test_environment_duplicate_slug_same_project_rejected(
    test_db_session: AsyncSession,
) -> None:
    """Verify duplicate environment slug under the same project is rejected."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org)
    await _create_test_environment(test_db_session, project, slug="production")

    dup = Environment(
        organization_id=org.id,
        project_id=project.id,
        name="Production Duplicate",
        slug="production",
    )
    test_db_session.add(dup)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_environment_same_slug_different_projects_allowed(
    test_db_session: AsyncSession,
) -> None:
    """Verify identical environment slug under different projects is allowed."""
    org = await _create_test_organization(test_db_session)
    proj1 = await _create_test_project(test_db_session, org, name="P1", slug="proj-1")
    proj2 = await _create_test_project(test_db_session, org, name="P2", slug="proj-2")

    env1 = await _create_test_environment(test_db_session, proj1, slug="production")
    env2 = await _create_test_environment(test_db_session, proj2, slug="production")

    assert env1.slug == env2.slug == "production"
    assert env1.id != env2.id
    assert env1.project_id != env2.project_id


# ==========================================
# 3. Service Tests
# ==========================================


@pytest.mark.asyncio
async def test_service_creation(test_db_session: AsyncSession) -> None:
    """Verify Service creation, field values, UUID, and timestamps."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org)
    env = await _create_test_environment(test_db_session, project)

    service = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env.id,
        name="Auth Gateway",
        slug="auth-gateway",
        description="OAuth2 and session token service",
        service_type=ServiceType.APPLICATION.value,
        is_active=True,
    )
    test_db_session.add(service)
    await test_db_session.commit()
    await test_db_session.refresh(service)

    assert isinstance(service.id, uuid.UUID)
    assert service.organization_id == org.id
    assert service.project_id == project.id
    assert service.environment_id == env.id
    assert service.name == "Auth Gateway"
    assert service.slug == "auth-gateway"
    assert service.service_type == "APPLICATION"
    assert service.is_active is True
    assert isinstance(service.created_at, datetime)
    assert isinstance(service.updated_at, datetime)


@pytest.mark.asyncio
async def test_service_relationships(test_db_session: AsyncSession) -> None:
    """Verify relationships between Service, Environment, Project, and Organization."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org)
    env = await _create_test_environment(test_db_session, project)

    service = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env.id,
        name="Ingestion Worker",
        slug="ingestion-worker",
        service_type=ServiceType.WORKER.value,
    )
    test_db_session.add(service)
    await test_db_session.commit()
    await test_db_session.refresh(service)

    assert service.environment.id == env.id
    assert service.project.id == project.id
    assert service.organization.id == org.id

    await test_db_session.refresh(env)
    assert any(s.id == service.id for s in env.services)


@pytest.mark.asyncio
async def test_service_duplicate_slug_same_environment_rejected(
    test_db_session: AsyncSession,
) -> None:
    """Verify duplicate service slug within the same environment is rejected."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org)
    env = await _create_test_environment(test_db_session, project)

    s1 = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env.id,
        name="Cache",
        slug="redis-cache",
        service_type=ServiceType.CACHE.value,
    )
    test_db_session.add(s1)
    await test_db_session.commit()

    s2 = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env.id,
        name="Another Cache",
        slug="redis-cache",
        service_type=ServiceType.CACHE.value,
    )
    test_db_session.add(s2)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_service_same_slug_different_environments_allowed(
    test_db_session: AsyncSession,
) -> None:
    """Verify same service slug under different environments is allowed."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org)
    env1 = await _create_test_environment(test_db_session, project, name="Dev", slug="dev")
    env2 = await _create_test_environment(test_db_session, project, name="Prod", slug="prod")

    s1 = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env1.id,
        name="API",
        slug="api",
        service_type=ServiceType.APPLICATION.value,
    )
    s2 = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env2.id,
        name="API",
        slug="api",
        service_type=ServiceType.APPLICATION.value,
    )
    test_db_session.add_all([s1, s2])
    await test_db_session.commit()

    assert s1.slug == s2.slug == "api"
    assert s1.id != s2.id
    assert s1.environment_id != s2.environment_id


@pytest.mark.asyncio
async def test_service_valid_service_types_accepted(test_db_session: AsyncSession) -> None:
    """Verify that all initial valid service types are accepted and persisted."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org)
    env = await _create_test_environment(test_db_session, project)

    expected_types = {"APPLICATION", "WORKER", "DATABASE", "CACHE", "QUEUE", "OTHER"}
    enum_types = {t.value for t in ServiceType}
    assert enum_types == expected_types

    for idx, st in enumerate(ServiceType):
        svc = Service(
            organization_id=org.id,
            project_id=project.id,
            environment_id=env.id,
            name=f"Service-{st.value}",
            slug=f"svc-{st.value.lower()}-{idx}",
            service_type=st.value,
        )
        test_db_session.add(svc)
        await test_db_session.commit()
        await test_db_session.refresh(svc)
        assert svc.service_type == st.value


@pytest.mark.asyncio
async def test_service_invalid_service_type_rejected(test_db_session: AsyncSession) -> None:
    """Verify that invalid service type is rejected at both model and database levels."""
    org = await _create_test_organization(test_db_session)
    project = await _create_test_project(test_db_session, org)
    env = await _create_test_environment(test_db_session, project)

    # 1. Model-level validation check
    with pytest.raises(ValueError) as exc_info:
        Service(
            organization_id=org.id,
            project_id=project.id,
            environment_id=env.id,
            name="Invalid Svc",
            slug="invalid-svc",
            service_type="UNSUPPORTED_TYPE",
        )
    assert "Invalid service_type" in str(exc_info.value)

    # 2. Database check constraint enforcement check (bypassing model validator via raw SQL)
    bad_id = uuid.uuid4()
    with pytest.raises(IntegrityError):
        await test_db_session.execute(
            text(
                "INSERT INTO services (id, organization_id, project_id, environment_id, name, slug, service_type, is_active, created_at, updated_at) "
                "VALUES (:id, :org_id, :proj_id, :env_id, :name, :slug, :service_type, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(bad_id),
                "org_id": str(org.id),
                "proj_id": str(project.id),
                "env_id": str(env.id),
                "name": "DB Check Svc",
                "slug": "db-check-svc",
                "service_type": "NON_EXISTENT_KIND",
            },
        )
        await test_db_session.commit()
    await test_db_session.rollback()


# ==========================================
# 4. Tenant Integrity Enforcement Tests
# ==========================================


@pytest.mark.asyncio
async def test_tenant_integrity_environment_org_mismatch_rejected(
    test_db_session: AsyncSession,
) -> None:
    """Verify that Environment cannot belong to Org B while its Project belongs to Org A."""
    org_a = await _create_test_organization(test_db_session, slug="org-a")
    org_b = await _create_test_organization(test_db_session, slug="org-b")
    proj_a = await _create_test_project(test_db_session, org_a, slug="proj-a")

    # Mismatched organization_id pointing to Org B while Project belongs to Org A
    invalid_env = Environment(
        organization_id=org_b.id,
        project_id=proj_a.id,
        name="Invalid Env",
        slug="invalid-env",
    )
    test_db_session.add(invalid_env)

    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_tenant_integrity_service_org_mismatch_rejected(
    test_db_session: AsyncSession,
) -> None:
    """Verify that Service cannot have organization_id != Environment.organization_id."""
    org_a = await _create_test_organization(test_db_session, slug="org-a-svc")
    org_b = await _create_test_organization(test_db_session, slug="org-b-svc")
    proj_a = await _create_test_project(test_db_session, org_a, slug="proj-a-svc")
    env_a = await _create_test_environment(test_db_session, proj_a, slug="env-a-svc")

    # Mismatched organization_id pointing to Org B
    invalid_service = Service(
        organization_id=org_b.id,
        project_id=proj_a.id,
        environment_id=env_a.id,
        name="Mismatched Org Service",
        slug="mismatched-org-svc",
        service_type=ServiceType.APPLICATION.value,
    )
    test_db_session.add(invalid_service)

    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_tenant_integrity_service_project_mismatch_rejected(
    test_db_session: AsyncSession,
) -> None:
    """Verify that Service cannot have project_id != Environment.project_id."""
    org = await _create_test_organization(test_db_session, slug="org-proj-mismatch")
    proj_a = await _create_test_project(test_db_session, org, name="Project A", slug="proj-a")
    proj_b = await _create_test_project(test_db_session, org, name="Project B", slug="proj-b")
    env_a = await _create_test_environment(test_db_session, proj_a, slug="env-a")

    # Service references Environment A (under Project A), but specifies Project B
    invalid_service = Service(
        organization_id=org.id,
        project_id=proj_b.id,
        environment_id=env_a.id,
        name="Mismatched Project Service",
        slug="mismatched-proj-svc",
        service_type=ServiceType.APPLICATION.value,
    )
    test_db_session.add(invalid_service)

    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


# ==========================================
# 5. Non-Destructive Deletion Lifecycle Tests
# ==========================================


@pytest.mark.asyncio
async def test_non_destructive_deletion_organization_with_projects_rejected(
    test_db_session: AsyncSession,
) -> None:
    """Verify that deleting an Organization with active projects is blocked by RESTRICT constraint."""
    org = await _create_test_organization(test_db_session, slug="org-restrict-test")
    await _create_test_project(test_db_session, org, slug="project-restrict-test")

    await test_db_session.delete(org)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_non_destructive_deletion_project_with_environments_rejected(
    test_db_session: AsyncSession,
) -> None:
    """Verify that deleting a Project with environments is blocked by RESTRICT constraint."""
    org = await _create_test_organization(test_db_session, slug="proj-restrict-test")
    project = await _create_test_project(test_db_session, org, slug="proj-with-env")
    await _create_test_environment(test_db_session, project, slug="env-child")

    await test_db_session.delete(project)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_non_destructive_deletion_environment_with_services_rejected(
    test_db_session: AsyncSession,
) -> None:
    """Verify that deleting an Environment with services is blocked by RESTRICT constraint."""
    org = await _create_test_organization(test_db_session, slug="env-restrict-test")
    project = await _create_test_project(test_db_session, org, slug="proj-for-env")
    env = await _create_test_environment(test_db_session, project, slug="env-for-svc")

    svc = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env.id,
        name="Worker Svc",
        slug="worker-svc",
        service_type=ServiceType.WORKER.value,
    )
    test_db_session.add(svc)
    await test_db_session.commit()

    await test_db_session.delete(env)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_soft_deactivation_lifecycle(test_db_session: AsyncSession) -> None:
    """Verify that is_active = False provides clean non-destructive operational lifecycle."""
    org = await _create_test_organization(test_db_session, slug="lifecycle-org")
    project = await _create_test_project(test_db_session, org, slug="lifecycle-proj")
    env = await _create_test_environment(test_db_session, project, slug="lifecycle-env")
    svc = Service(
        organization_id=org.id,
        project_id=project.id,
        environment_id=env.id,
        name="Lifecycle Svc",
        slug="lifecycle-svc",
        service_type=ServiceType.APPLICATION.value,
    )
    test_db_session.add(svc)
    await test_db_session.commit()

    # Soft deactivate service, environment, project
    svc.is_active = False
    env.is_active = False
    project.is_active = False
    await test_db_session.commit()

    await test_db_session.refresh(svc)
    await test_db_session.refresh(env)
    await test_db_session.refresh(project)

    assert svc.is_active is False
    assert env.is_active is False
    assert project.is_active is False
    # Data is fully preserved
    assert svc.name == "Lifecycle Svc"
    assert env.name == "Production"
    assert project.name == "Core Platform"
