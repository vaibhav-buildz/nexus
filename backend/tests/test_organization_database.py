"""Database-level integration tests for Organization and OrganizationMember models."""

from datetime import datetime, timezone
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember, OrgRole
from app.models.user import User


async def _create_test_user(
    db: AsyncSession,
    email: str | None = None,
) -> User:
    """Helper to create a user for database testing."""
    user = User(
        email=email or f"user_{uuid.uuid4().hex[:8]}@nexus.internal",
        password_hash="argon2id_dummy_hash_for_db_tests",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_organization_creation(test_db_session: AsyncSession) -> None:
    """Verify Organization model creation, fields, defaults, and slug uniqueness."""
    org = Organization(
        name="Acme Reliability Corp",
        slug="acme-reliability",
        description="Core infrastructure monitoring team",
        is_active=True,
    )
    test_db_session.add(org)
    await test_db_session.commit()
    await test_db_session.refresh(org)

    assert isinstance(org.id, uuid.UUID)
    assert org.name == "Acme Reliability Corp"
    assert org.slug == "acme-reliability"
    assert org.description == "Core infrastructure monitoring team"
    assert org.is_active is True
    assert isinstance(org.created_at, datetime)
    assert isinstance(org.updated_at, datetime)

    # Verify duplicate slug is rejected
    duplicate_org = Organization(
        name="Another Acme",
        slug="acme-reliability",  # Same slug
        description="Duplicate slug test",
    )
    test_db_session.add(duplicate_org)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_membership_creation_and_relationships(test_db_session: AsyncSession) -> None:
    """Verify OrganizationMember creation and bi-directional relationships with User and Org."""
    user = await _create_test_user(test_db_session)
    org = Organization(name="FinTech Ops", slug="fintech-ops")
    test_db_session.add(org)
    await test_db_session.commit()
    await test_db_session.refresh(org)

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrgRole.OWNER.value,
    )
    test_db_session.add(member)
    await test_db_session.commit()
    await test_db_session.refresh(member)

    assert isinstance(member.id, uuid.UUID)
    assert member.organization_id == org.id
    assert member.user_id == user.id
    assert member.role == OrgRole.OWNER.value
    assert isinstance(member.created_at, datetime)
    assert isinstance(member.updated_at, datetime)

    # Verify relationships
    await test_db_session.refresh(org)
    await test_db_session.refresh(user)

    assert len(org.members) == 1
    assert org.members[0].id == member.id
    assert org.members[0].role == OrgRole.OWNER.value

    assert len(user.organization_memberships) == 1
    assert user.organization_memberships[0].id == member.id
    assert user.organization_memberships[0].organization_id == org.id


@pytest.mark.asyncio
async def test_foreign_key_constraints(test_db_session: AsyncSession) -> None:
    """Verify that OrganizationMember enforces valid foreign keys to User and Organization."""
    valid_user = await _create_test_user(test_db_session)
    valid_org = Organization(name="SecOps", slug="sec-ops")
    test_db_session.add(valid_org)
    await test_db_session.commit()

    valid_user_id = valid_user.id
    valid_org_id = valid_org.id

    # Invalid organization_id
    invalid_org_member = OrganizationMember(
        organization_id=uuid.uuid4(),  # Non-existent org
        user_id=valid_user_id,
        role=OrgRole.MEMBER.value,
    )
    test_db_session.add(invalid_org_member)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()

    # Invalid user_id
    invalid_user_member = OrganizationMember(
        organization_id=valid_org_id,
        user_id=uuid.uuid4(),  # Non-existent user
        role=OrgRole.MEMBER.value,
    )
    test_db_session.add(invalid_user_member)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_duplicate_membership_rejection(test_db_session: AsyncSession) -> None:
    """Verify composite unique constraint prevents duplicate membership for (org_id, user_id)."""
    user = await _create_test_user(test_db_session)
    org = Organization(name="Data Infrastructure", slug="data-infra")
    test_db_session.add(org)
    await test_db_session.commit()

    # First membership
    member1 = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrgRole.ADMIN.value,
    )
    test_db_session.add(member1)
    await test_db_session.commit()

    # Attempt second membership for same org and user
    member2 = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrgRole.VIEWER.value,
    )
    test_db_session.add(member2)
    with pytest.raises(IntegrityError):
        await test_db_session.commit()
    await test_db_session.rollback()


@pytest.mark.asyncio
async def test_one_user_multiple_organizations(test_db_session: AsyncSession) -> None:
    """Verify that a single user can belong to multiple organizations with differing roles."""
    user = await _create_test_user(test_db_session)

    org_a = Organization(name="Org Alpha", slug="org-alpha")
    org_b = Organization(name="Org Beta", slug="org-beta")
    org_c = Organization(name="Org Gamma", slug="org-gamma")
    test_db_session.add_all([org_a, org_b, org_c])
    await test_db_session.commit()

    # User is OWNER in Org A, ADMIN in Org B, and VIEWER in Org C
    m_a = OrganizationMember(organization_id=org_a.id, user_id=user.id, role=OrgRole.OWNER.value)
    m_b = OrganizationMember(organization_id=org_b.id, user_id=user.id, role=OrgRole.ADMIN.value)
    m_c = OrganizationMember(organization_id=org_c.id, user_id=user.id, role=OrgRole.VIEWER.value)
    test_db_session.add_all([m_a, m_b, m_c])
    await test_db_session.commit()

    # Query memberships for user
    res = await test_db_session.scalars(
        select(OrganizationMember).where(OrganizationMember.user_id == user.id)
    )
    user_memberships = res.all()
    assert len(user_memberships) == 3

    roles_by_org = {m.organization_id: m.role for m in user_memberships}
    assert roles_by_org[org_a.id] == OrgRole.OWNER.value
    assert roles_by_org[org_b.id] == OrgRole.ADMIN.value
    assert roles_by_org[org_c.id] == OrgRole.VIEWER.value


@pytest.mark.asyncio
async def test_multiple_users_one_organization(test_db_session: AsyncSession) -> None:
    """Verify that multiple users can belong to a single organization with different roles."""
    org = Organization(name="Platform Engineering", slug="platform-eng")
    test_db_session.add(org)
    await test_db_session.commit()

    user1 = await _create_test_user(test_db_session, "owner@nexus.internal")
    user2 = await _create_test_user(test_db_session, "admin@nexus.internal")
    user3 = await _create_test_user(test_db_session, "member@nexus.internal")
    user4 = await _create_test_user(test_db_session, "viewer@nexus.internal")

    m1 = OrganizationMember(organization_id=org.id, user_id=user1.id, role=OrgRole.OWNER.value)
    m2 = OrganizationMember(organization_id=org.id, user_id=user2.id, role=OrgRole.ADMIN.value)
    m3 = OrganizationMember(organization_id=org.id, user_id=user3.id, role=OrgRole.MEMBER.value)
    m4 = OrganizationMember(organization_id=org.id, user_id=user4.id, role=OrgRole.VIEWER.value)
    test_db_session.add_all([m1, m2, m3, m4])
    await test_db_session.commit()

    res = await test_db_session.scalars(
        select(OrganizationMember).where(OrganizationMember.organization_id == org.id)
    )
    members = res.all()
    assert len(members) == 4

    roles_by_user = {m.user_id: m.role for m in members}
    assert roles_by_user[user1.id] == OrgRole.OWNER.value
    assert roles_by_user[user2.id] == OrgRole.ADMIN.value
    assert roles_by_user[user3.id] == OrgRole.MEMBER.value
    assert roles_by_user[user4.id] == OrgRole.VIEWER.value


@pytest.mark.asyncio
async def test_role_enum_values_and_representations(test_db_session: AsyncSession) -> None:
    """Verify the controlled application-level OrgRole enum values and persistence."""
    expected_roles = {"OWNER", "ADMIN", "MEMBER", "VIEWER"}
    enum_roles = {role.value for role in OrgRole}
    assert enum_roles == expected_roles

    # Verify each role can be assigned and persists properly
    org = Organization(name="Roles Test Org", slug="roles-test-org")
    test_db_session.add(org)
    await test_db_session.commit()

    for role in OrgRole:
        user = await _create_test_user(test_db_session)
        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=role.value,
        )
        test_db_session.add(member)
        await test_db_session.commit()
        await test_db_session.refresh(member)
        assert member.role == role.value


@pytest.mark.asyncio
async def test_cascade_delete_organization(test_db_session: AsyncSession) -> None:
    """Verify deleting an Organization cascades to delete its members, but preserves Users."""
    user1 = await _create_test_user(test_db_session)
    user2 = await _create_test_user(test_db_session)

    org = Organization(name="Ephemeral Org", slug="ephemeral-org")
    test_db_session.add(org)
    await test_db_session.commit()

    m1 = OrganizationMember(organization_id=org.id, user_id=user1.id, role=OrgRole.OWNER.value)
    m2 = OrganizationMember(organization_id=org.id, user_id=user2.id, role=OrgRole.MEMBER.value)
    test_db_session.add_all([m1, m2])
    await test_db_session.commit()

    # Delete organization
    await test_db_session.delete(org)
    await test_db_session.commit()

    # Verify memberships are deleted
    memberships = (
        await test_db_session.scalars(
            select(OrganizationMember).where(OrganizationMember.organization_id == org.id)
        )
    ).all()
    assert len(memberships) == 0

    # Verify users still exist
    u1_db = await test_db_session.scalar(select(User).where(User.id == user1.id))
    u2_db = await test_db_session.scalar(select(User).where(User.id == user2.id))
    assert u1_db is not None
    assert u2_db is not None


@pytest.mark.asyncio
async def test_cascade_delete_user(test_db_session: AsyncSession) -> None:
    """Verify deleting a User cascades to delete their memberships, but preserves Organizations."""
    user = await _create_test_user(test_db_session)
    org1 = Organization(name="Keep Org 1", slug="keep-org-1")
    org2 = Organization(name="Keep Org 2", slug="keep-org-2")
    test_db_session.add_all([org1, org2])
    await test_db_session.commit()

    m1 = OrganizationMember(organization_id=org1.id, user_id=user.id, role=OrgRole.OWNER.value)
    m2 = OrganizationMember(organization_id=org2.id, user_id=user.id, role=OrgRole.MEMBER.value)
    test_db_session.add_all([m1, m2])
    await test_db_session.commit()

    # Delete user
    await test_db_session.delete(user)
    await test_db_session.commit()

    # Verify memberships are deleted
    memberships = (
        await test_db_session.scalars(
            select(OrganizationMember).where(OrganizationMember.user_id == user.id)
        )
    ).all()
    assert len(memberships) == 0

    # Verify organizations still exist
    o1_db = await test_db_session.scalar(select(Organization).where(Organization.id == org1.id))
    o2_db = await test_db_session.scalar(select(Organization).where(Organization.id == org2.id))
    assert o1_db is not None
    assert o2_db is not None


@pytest.mark.asyncio
async def test_composite_membership_role_index(test_db_session: AsyncSession) -> None:
    """Verify that OrganizationMember defines the composite index on (organization_id, role)."""
    table = OrganizationMember.__table__
    index_names = {idx.name: [c.name for c in idx.columns] for idx in table.indexes}

    assert "ix_organization_members_organization_id_role" in index_names
    indexed_columns = index_names["ix_organization_members_organization_id_role"]
    assert indexed_columns == ["organization_id", "role"]

