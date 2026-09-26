"""Integration tests for NEXUS Organization APIs, multi-tenancy, and RBAC enforcement."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.rbac import OrgRole
from app.core.security import create_access_token
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


async def _create_user(
    db: AsyncSession,
    email: str | None = None,
    is_active: bool = True,
    is_verified: bool = True,
) -> User:
    """Helper to create and persist a test user."""
    user = User(
        email=email or f"user_{uuid.uuid4().hex[:8]}@nexus.internal",
        password_hash="argon2id_dummy_hash",
        is_active=is_active,
        is_verified=is_verified,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


def _auth_header(user: User) -> dict[str, str]:
    """Helper generating bearer authorization header for a user."""
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_organization_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify organization creation, field validation, and response schema."""
    user = await _create_user(test_db_session)
    await test_db_session.commit()

    payload = {
        "name": "Acme Monitoring Corp",
        "slug": "acme-monitoring",
        "description": "Enterprise reliability monitoring",
    }
    response = await client.post(
        "/api/v1/organizations",
        json=payload,
        headers=_auth_header(user),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Acme Monitoring Corp"
    assert data["slug"] == "acme-monitoring"
    assert data["description"] == "Enterprise reliability monitoring"
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data

    # Verify database persistence
    org_id = uuid.UUID(data["id"])
    db_org = await test_db_session.scalar(select(Organization).where(Organization.id == org_id))
    assert db_org is not None
    assert db_org.name == "Acme Monitoring Corp"
    assert db_org.slug == "acme-monitoring"


@pytest.mark.asyncio
async def test_creator_becomes_owner(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that creating an organization automatically assigns creator the OWNER role."""
    creator = await _create_user(test_db_session)
    await test_db_session.commit()

    response = await client.post(
        "/api/v1/organizations",
        json={"name": "Owner Org", "slug": "owner-org"},
        headers=_auth_header(creator),
    )
    assert response.status_code == 201
    org_id = uuid.UUID(response.json()["id"])

    # Query membership
    membership = await test_db_session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == creator.id,
        )
    )
    assert membership is not None
    assert membership.role == OrgRole.OWNER.value


@pytest.mark.asyncio
async def test_atomic_creation_rollback(
    test_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that if membership creation fails, the organization is rolled back atomically."""
    user = await _create_user(test_db_session)
    await test_db_session.commit()

    from app.schemas.organization import OrganizationCreateRequest
    from app.services.organization_service import OrganizationService

    original_add = test_db_session.add

    def failing_add(instance):
        if isinstance(instance, OrganizationMember):
            raise RuntimeError("Simulated transaction failure during membership insertion")
        original_add(instance)

    monkeypatch.setattr(test_db_session, "add", failing_add)

    payload = OrganizationCreateRequest(name="Failed Org", slug="failed-org")

    with pytest.raises(RuntimeError, match="Simulated transaction failure during membership insertion"):
        await OrganizationService.create_organization(
            db=test_db_session,
            creator=user,
            payload=payload,
        )

    # Verify that 'failed-org' does NOT exist in the database (rolled back)
    persisted_org = await test_db_session.scalar(
        select(Organization).where(Organization.slug == "failed-org")
    )
    assert persisted_org is None


@pytest.mark.asyncio
async def test_duplicate_slug_conflict(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify duplicate slug violates uniqueness and returns 409 conflict envelope."""
    user1 = await _create_user(test_db_session)
    user2 = await _create_user(test_db_session)
    await test_db_session.commit()

    # Create first org
    res1 = await client.post(
        "/api/v1/organizations",
        json={"name": "First Org", "slug": "shared-slug"},
        headers=_auth_header(user1),
    )
    assert res1.status_code == 201

    # Attempt to create second org with identical slug
    res2 = await client.post(
        "/api/v1/organizations",
        json={"name": "Second Org", "slug": "shared-slug"},
        headers=_auth_header(user2),
    )
    assert res2.status_code == 409
    data = res2.json()
    assert data["error"]["code"] == "ORGANIZATION_ALREADY_EXISTS"
    assert data["error"]["message"] == "An organization with this slug already exists."


@pytest.mark.asyncio
async def test_list_only_user_organizations(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that GET /organizations returns ONLY organizations the user belongs to."""
    user_a = await _create_user(test_db_session, "user_a@test.internal")
    user_b = await _create_user(test_db_session, "user_b@test.internal")
    await test_db_session.commit()

    # User A creates Org 1 & Org 2
    res_a1 = await client.post(
        "/api/v1/organizations",
        json={"name": "User A Org 1", "slug": "user-a-org-1"},
        headers=_auth_header(user_a),
    )
    res_a2 = await client.post(
        "/api/v1/organizations",
        json={"name": "User A Org 2", "slug": "user-a-org-2"},
        headers=_auth_header(user_a),
    )
    assert res_a1.status_code == 201
    assert res_a2.status_code == 201

    # User B creates Org 3
    res_b = await client.post(
        "/api/v1/organizations",
        json={"name": "User B Org 3", "slug": "user-b-org-3"},
        headers=_auth_header(user_b),
    )
    assert res_b.status_code == 201

    # User A lists orgs: must only see Org 1 and Org 2
    list_a = await client.get("/api/v1/organizations", headers=_auth_header(user_a))
    assert list_a.status_code == 200
    orgs_a = list_a.json()
    slugs_a = [o["slug"] for o in orgs_a]
    assert "user-a-org-1" in slugs_a
    assert "user-a-org-2" in slugs_a
    assert "user-b-org-3" not in slugs_a
    assert len(orgs_a) == 2

    # User B lists orgs: must only see Org 3
    list_b = await client.get("/api/v1/organizations", headers=_auth_header(user_b))
    assert list_b.status_code == 200
    orgs_b = list_b.json()
    slugs_b = [o["slug"] for o in orgs_b]
    assert "user-b-org-3" in slugs_b
    assert "user-a-org-1" not in slugs_b
    assert "user-a-org-2" not in slugs_b
    assert len(orgs_b) == 1


@pytest.mark.asyncio
async def test_get_organization_member_access(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that a member can access their organization details via GET /{org_id}."""
    user = await _create_user(test_db_session)
    await test_db_session.commit()

    create_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Detail Org", "slug": "detail-org", "description": "Org details"},
        headers=_auth_header(user),
    )
    org_id = create_res.json()["id"]

    res = await client.get(
        f"/api/v1/organizations/{org_id}",
        headers=_auth_header(user),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == org_id
    assert data["name"] == "Detail Org"
    assert data["slug"] == "detail-org"
    assert data["description"] == "Org details"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_get_organization_non_member_access(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that a non-member receives 404 to prevent tenant enumeration."""
    owner = await _create_user(test_db_session)
    outsider = await _create_user(test_db_session)
    await test_db_session.commit()

    create_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Private Org", "slug": "private-org"},
        headers=_auth_header(owner),
    )
    org_id = create_res.json()["id"]

    # Outsider attempts to get org details
    res = await client.get(
        f"/api/v1/organizations/{org_id}",
        headers=_auth_header(outsider),
    )
    assert res.status_code == 404
    data = res.json()
    assert data["error"]["code"] == "ORGANIZATION_NOT_FOUND"
    assert data["error"]["message"] == "Organization not found."

    # Non-existent org ID must return identical 404
    random_id = uuid.uuid4()
    res_rand = await client.get(
        f"/api/v1/organizations/{random_id}",
        headers=_auth_header(outsider),
    )
    assert res_rand.status_code == 404
    assert res_rand.json()["error"]["code"] == "ORGANIZATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_inactive_organization_forbidden(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that accessing an inactive organization returns 403 ORGANIZATION_INACTIVE."""
    user = await _create_user(test_db_session)
    await test_db_session.commit()

    create_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Deactivated Org", "slug": "deactivated-org"},
        headers=_auth_header(user),
    )
    org_id = uuid.UUID(create_res.json()["id"])

    # Deactivate in DB
    db_org = await test_db_session.scalar(select(Organization).where(Organization.id == org_id))
    db_org.is_active = False
    await test_db_session.commit()

    res = await client.get(
        f"/api/v1/organizations/{org_id}",
        headers=_auth_header(user),
    )
    assert res.status_code == 403
    data = res.json()
    assert data["error"]["code"] == "ORGANIZATION_INACTIVE"
    assert data["error"]["message"] == "Organization is inactive."


@pytest.mark.asyncio
async def test_update_organization_authorization(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify PATCH permissions: OWNER & ADMIN can update, MEMBER/VIEWER/non-members cannot."""
    owner = await _create_user(test_db_session, "owner@corp.internal")
    admin = await _create_user(test_db_session, "admin@corp.internal")
    member = await _create_user(test_db_session, "member@corp.internal")
    viewer = await _create_user(test_db_session, "viewer@corp.internal")
    outsider = await _create_user(test_db_session, "outsider@other.internal")
    await test_db_session.commit()

    create_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Initial Name", "slug": "patch-test-org", "description": "Initial desc"},
        headers=_auth_header(owner),
    )
    org_id = uuid.UUID(create_res.json()["id"])

    # Add other members
    m_admin = OrganizationMember(organization_id=org_id, user_id=admin.id, role=OrgRole.ADMIN.value)
    m_member = OrganizationMember(organization_id=org_id, user_id=member.id, role=OrgRole.MEMBER.value)
    m_viewer = OrganizationMember(organization_id=org_id, user_id=viewer.id, role=OrgRole.VIEWER.value)
    test_db_session.add_all([m_admin, m_member, m_viewer])
    await test_db_session.commit()

    # 1. VIEWER cannot update -> 403
    res_v = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Viewer Edit"},
        headers=_auth_header(viewer),
    )
    assert res_v.status_code == 403
    assert res_v.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # 2. MEMBER cannot update -> 403
    res_m = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Member Edit"},
        headers=_auth_header(member),
    )
    assert res_m.status_code == 403

    # 3. Outsider cannot update -> 404 (no existence leak)
    res_o = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Outsider Edit"},
        headers=_auth_header(outsider),
    )
    assert res_o.status_code == 404

    # 4. ADMIN can update -> 200
    res_a = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Admin Updated Name", "description": "Admin updated desc"},
        headers=_auth_header(admin),
    )
    assert res_a.status_code == 200
    assert res_a.json()["name"] == "Admin Updated Name"
    assert res_a.json()["description"] == "Admin updated desc"

    # 5. OWNER can update -> 200
    res_ow = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Owner Final Name"},
        headers=_auth_header(owner),
    )
    assert res_ow.status_code == 200
    assert res_ow.json()["name"] == "Owner Final Name"

    # 6. Reject arbitrary model field updates (e.g. is_active or id)
    res_bad = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"is_active": False},
        headers=_auth_header(owner),
    )
    assert res_bad.status_code == 422


@pytest.mark.asyncio
async def test_delete_deactivation_authorization(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify DELETE deactivates organization (is_active=False) and preserves data."""
    owner = await _create_user(test_db_session)
    await test_db_session.commit()

    create_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Deactivate Me", "slug": "deactivate-me"},
        headers=_auth_header(owner),
    )
    org_id = uuid.UUID(create_res.json()["id"])

    # Perform DELETE
    del_res = await client.delete(
        f"/api/v1/organizations/{org_id}",
        headers=_auth_header(owner),
    )
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False

    # Verify database record still exists safely (no destructive cascade deletion)
    db_org = await test_db_session.scalar(select(Organization).where(Organization.id == org_id))
    assert db_org is not None
    assert db_org.is_active is False

    # Verify membership still exists
    db_member = await test_db_session.scalar(
        select(OrganizationMember).where(OrganizationMember.organization_id == org_id)
    )
    assert db_member is not None

    # Subsequent GET returns 403 inactive
    get_res = await client.get(
        f"/api/v1/organizations/{org_id}",
        headers=_auth_header(owner),
    )
    assert get_res.status_code == 403
    assert get_res.json()["error"]["code"] == "ORGANIZATION_INACTIVE"


@pytest.mark.asyncio
async def test_owner_vs_admin_behavior(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Explicitly verify OWNER vs ADMIN behavior on PATCH and DELETE endpoints."""
    owner = await _create_user(test_db_session, "super_owner@nexus.internal")
    admin = await _create_user(test_db_session, "super_admin@nexus.internal")
    await test_db_session.commit()

    create_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Owner vs Admin", "slug": "owner-vs-admin"},
        headers=_auth_header(owner),
    )
    org_id = uuid.UUID(create_res.json()["id"])

    m_admin = OrganizationMember(organization_id=org_id, user_id=admin.id, role=OrgRole.ADMIN.value)
    test_db_session.add(m_admin)
    await test_db_session.commit()

    # ADMIN can PATCH org
    admin_patch = await client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"name": "Updated by Admin"},
        headers=_auth_header(admin),
    )
    assert admin_patch.status_code == 200

    # ADMIN CANNOT DELETE org -> 403 Insufficient permissions
    admin_delete = await client.delete(
        f"/api/v1/organizations/{org_id}",
        headers=_auth_header(admin),
    )
    assert admin_delete.status_code == 403
    assert admin_delete.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # OWNER CAN DELETE org -> 200 OK
    owner_delete = await client.delete(
        f"/api/v1/organizations/{org_id}",
        headers=_auth_header(owner),
    )
    assert owner_delete.status_code == 200
    assert owner_delete.json()["is_active"] is False
