"""Integration tests for organization membership management and governance enforcement."""

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
    """Helper creating a test user."""
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


async def _create_org_with_owner(
    db: AsyncSession,
    owner: User,
    slug: str | None = None,
) -> Organization:
    """Helper creating an organization with the given user as OWNER."""
    org = Organization(
        name="Test Workspace",
        slug=slug or f"org-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    db.add(org)
    await db.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=owner.id,
        role=OrgRole.OWNER.value,
    )
    db.add(member)
    await db.commit()
    await db.refresh(org)
    return org


def _auth_header(user: User) -> dict[str, str]:
    """Helper returning authorization header."""
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_add_member_by_email_and_by_id(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify adding members by email and by user_id."""
    owner = await _create_user(test_db_session)
    user1 = await _create_user(test_db_session, "user1@nexus.internal")
    user2 = await _create_user(test_db_session, "user2@nexus.internal")
    org = await _create_org_with_owner(test_db_session, owner)

    # 1. Add user1 by email with MEMBER role
    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"email": user1.email, "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["user_id"] == str(user1.id)
    assert data1["email"] == user1.email
    assert data1["role"] == OrgRole.MEMBER.value
    assert data1["organization_id"] == str(org.id)

    # 2. Add user2 by user_id with ADMIN role
    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(user2.id), "role": OrgRole.ADMIN.value},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["user_id"] == str(user2.id)
    assert data2["email"] == user2.email
    assert data2["role"] == OrgRole.ADMIN.value


@pytest.mark.asyncio
async def test_duplicate_member(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify duplicate member addition is rejected with 409 conflict."""
    owner = await _create_user(test_db_session)
    user = await _create_user(test_db_session)
    org = await _create_org_with_owner(test_db_session, owner)

    # Add member first time
    res1 = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(user.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 201

    # Attempt to add same member second time
    res2 = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(user.id), "role": OrgRole.VIEWER.value},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 409
    data = res2.json()
    assert data["error"]["code"] == "MEMBER_ALREADY_EXISTS"
    assert data["error"]["message"] == "User is already a member of this organization."


@pytest.mark.asyncio
async def test_list_members(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify GET /members returns all members of the organization with user emails."""
    owner = await _create_user(test_db_session, "owner@corp.internal")
    member = await _create_user(test_db_session, "member@corp.internal")
    org = await _create_org_with_owner(test_db_session, owner)

    # Add member
    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(member.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )

    res = await client.get(
        f"/api/v1/organizations/{org.id}/members",
        headers=_auth_header(member),
    )
    assert res.status_code == 200
    members = res.json()
    assert len(members) == 2
    emails = {m["email"] for m in members}
    assert "owner@corp.internal" in emails
    assert "member@corp.internal" in emails


@pytest.mark.asyncio
async def test_remove_member(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify OWNER can remove a member from the organization."""
    owner = await _create_user(test_db_session)
    member = await _create_user(test_db_session)
    org = await _create_org_with_owner(test_db_session, owner)

    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(member.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )

    # Remove member
    res = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        headers=_auth_header(owner),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Verify member is gone
    check_member = await test_db_session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == member.id,
        )
    )
    assert check_member is None


@pytest.mark.asyncio
async def test_self_leave(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify a non-owner member can leave an organization (self-leave)."""
    owner = await _create_user(test_db_session)
    member = await _create_user(test_db_session)
    org = await _create_org_with_owner(test_db_session, owner)

    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(member.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )

    # Member removes themselves
    res = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        headers=_auth_header(member),
    )
    assert res.status_code == 200

    # Verify member is no longer in the organization
    check_member = await test_db_session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == member.id,
        )
    )
    assert check_member is None


@pytest.mark.asyncio
async def test_role_changes(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify updating a member's role (MEMBER -> ADMIN -> VIEWER)."""
    owner = await _create_user(test_db_session)
    user = await _create_user(test_db_session)
    org = await _create_org_with_owner(test_db_session, owner)

    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(user.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )

    # Update to ADMIN
    res1 = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{user.id}",
        json={"role": OrgRole.ADMIN.value},
        headers=_auth_header(owner),
    )
    assert res1.status_code == 200
    assert res1.json()["role"] == OrgRole.ADMIN.value

    # Update to VIEWER
    res2 = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{user.id}",
        json={"role": OrgRole.VIEWER.value},
        headers=_auth_header(owner),
    )
    assert res2.status_code == 200
    assert res2.json()["role"] == OrgRole.VIEWER.value


@pytest.mark.asyncio
async def test_admin_restrictions(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify ADMIN restrictions: cannot assign OWNER, promote to OWNER, modify OWNER, or remove OWNER."""
    owner = await _create_user(test_db_session, "owner@test.internal")
    admin = await _create_user(test_db_session, "admin@test.internal")
    member = await _create_user(test_db_session, "member@test.internal")
    new_user = await _create_user(test_db_session, "new_user@test.internal")
    org = await _create_org_with_owner(test_db_session, owner)

    # Add admin and member
    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(admin.id), "role": OrgRole.ADMIN.value},
        headers=_auth_header(owner),
    )
    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(member.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )

    # 1. ADMIN cannot add new member with OWNER role -> 403
    res_add_owner = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(new_user.id), "role": OrgRole.OWNER.value},
        headers=_auth_header(admin),
    )
    assert res_add_owner.status_code == 403

    # 2. ADMIN cannot promote Member to OWNER -> 403
    res_promote_owner = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        json={"role": OrgRole.OWNER.value},
        headers=_auth_header(admin),
    )
    assert res_promote_owner.status_code == 403

    # 3. ADMIN cannot modify OWNER's role -> 403
    res_mod_owner = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{owner.id}",
        json={"role": OrgRole.MEMBER.value},
        headers=_auth_header(admin),
    )
    assert res_mod_owner.status_code == 403

    # 4. ADMIN cannot remove an OWNER -> 403
    res_del_owner = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{owner.id}",
        headers=_auth_header(admin),
    )
    assert res_del_owner.status_code == 403

    # 5. ADMIN CAN remove a regular MEMBER -> 200
    res_del_member = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        headers=_auth_header(admin),
    )
    assert res_del_member.status_code == 200


@pytest.mark.asyncio
async def test_owner_restrictions_and_self_escalation(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify self-privilege escalation prevention: a user cannot escalate their own role."""
    owner = await _create_user(test_db_session)
    admin = await _create_user(test_db_session)
    member = await _create_user(test_db_session)
    org = await _create_org_with_owner(test_db_session, owner)

    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(admin.id), "role": OrgRole.ADMIN.value},
        headers=_auth_header(owner),
    )
    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(member.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )

    # Member attempts to promote self to ADMIN -> 403 (member:role_update permission denied)
    res_m = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        json={"role": OrgRole.ADMIN.value},
        headers=_auth_header(member),
    )
    assert res_m.status_code == 403

    # Admin attempts to promote self to OWNER -> 403 (governance rule prevents self escalation)
    res_a = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{admin.id}",
        json={"role": OrgRole.OWNER.value},
        headers=_auth_header(admin),
    )
    assert res_a.status_code == 403


@pytest.mark.asyncio
async def test_last_owner_protection(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that a sole OWNER cannot be demoted, removed, or leave."""
    owner = await _create_user(test_db_session)
    org = await _create_org_with_owner(test_db_session, owner)

    # 1. Sole owner attempts to demote self to ADMIN -> 403
    res_demote = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{owner.id}",
        json={"role": OrgRole.ADMIN.value},
        headers=_auth_header(owner),
    )
    assert res_demote.status_code == 403

    # 2. Sole owner attempts to leave / delete self -> 403
    res_leave = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{owner.id}",
        headers=_auth_header(owner),
    )
    assert res_leave.status_code == 403
    assert res_leave.json()["error"]["code"] == "GOVERNANCE_RULE_VIOLATION"


@pytest.mark.asyncio
async def test_multiple_owners(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that when multiple owners exist, one owner can demote or remove another."""
    owner_a = await _create_user(test_db_session, "owner_a@nexus.internal")
    owner_b = await _create_user(test_db_session, "owner_b@nexus.internal")
    org = await _create_org_with_owner(test_db_session, owner_a)

    # Owner A promotes Owner B to OWNER
    res_add = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(owner_b.id), "role": OrgRole.OWNER.value},
        headers=_auth_header(owner_a),
    )
    assert res_add.status_code == 201
    assert res_add.json()["role"] == OrgRole.OWNER.value

    # Now there are 2 owners. Owner A demotes Owner B to ADMIN -> 200 OK
    res_demote = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{owner_b.id}",
        json={"role": OrgRole.ADMIN.value},
        headers=_auth_header(owner_a),
    )
    assert res_demote.status_code == 200
    assert res_demote.json()["role"] == OrgRole.ADMIN.value

    # Now Owner A is the sole owner again. Owner A attempts to leave -> 403
    res_leave = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{owner_a.id}",
        headers=_auth_header(owner_a),
    )
    assert res_leave.status_code == 403


@pytest.mark.asyncio
async def test_cross_tenant_member_manipulation(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify tenant isolation: members cannot be viewed, added, modified, or removed across orgs."""
    owner_1 = await _create_user(test_db_session, "owner1@corp.internal")
    owner_2 = await _create_user(test_db_session, "owner2@corp.internal")
    victim = await _create_user(test_db_session, "victim@corp.internal")

    org_1 = await _create_org_with_owner(test_db_session, owner_1, "org-one")
    org_2 = await _create_org_with_owner(test_db_session, owner_2, "org-two")

    # Add victim to Org 2
    await client.post(
        f"/api/v1/organizations/{org_2.id}/members",
        json={"user_id": str(victim.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner_2),
    )

    # Owner 1 attempts to list members of Org 2 -> 404 (non-member)
    res_list = await client.get(
        f"/api/v1/organizations/{org_2.id}/members",
        headers=_auth_header(owner_1),
    )
    assert res_list.status_code == 404

    # Owner 1 attempts to modify victim via Org 1 context (where victim is not a member) -> 404
    res_patch = await client.patch(
        f"/api/v1/organizations/{org_1.id}/members/{victim.id}",
        json={"role": OrgRole.ADMIN.value},
        headers=_auth_header(owner_1),
    )
    assert res_patch.status_code == 404
    assert res_patch.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    # Owner 1 attempts to remove victim via Org 1 context -> 404
    res_del = await client.delete(
        f"/api/v1/organizations/{org_1.id}/members/{victim.id}",
        headers=_auth_header(owner_1),
    )
    assert res_del.status_code == 404


@pytest.mark.asyncio
async def test_inactive_and_nonexistent_users(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify handling of inactive and nonexistent users."""
    owner = await _create_user(test_db_session)
    inactive_user = await _create_user(test_db_session, is_active=False)
    org = await _create_org_with_owner(test_db_session, owner)

    # 1. Attempting to add an inactive user -> 403 USER_INACTIVE
    res_inactive = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(inactive_user.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )
    assert res_inactive.status_code == 403
    assert res_inactive.json()["error"]["code"] == "USER_INACTIVE"

    # 2. Attempting to add a nonexistent user by UUID -> 404 USER_NOT_FOUND
    random_user_id = uuid.uuid4()
    res_nonexistent = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(random_user_id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )
    assert res_nonexistent.status_code == 404
    assert res_nonexistent.json()["error"]["code"] == "USER_NOT_FOUND"

    # 3. Attempting to add a nonexistent user by email -> 404 USER_NOT_FOUND
    res_nonexistent_email = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"email": "nobody@nowhere.com", "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )
    assert res_nonexistent_email.status_code == 404
    assert res_nonexistent_email.json()["error"]["code"] == "USER_NOT_FOUND"

    # 4. Modifying nonexistent member -> 404 MEMBER_NOT_FOUND
    res_mod_nonexistent = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{random_user_id}",
        json={"role": OrgRole.ADMIN.value},
        headers=_auth_header(owner),
    )
    assert res_mod_nonexistent.status_code == 404
    assert res_mod_nonexistent.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    # 5. Removing nonexistent member -> 404 MEMBER_NOT_FOUND
    res_del_nonexistent = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{random_user_id}",
        headers=_auth_header(owner),
    )
    assert res_del_nonexistent.status_code == 404
    assert res_del_nonexistent.json()["error"]["code"] == "MEMBER_NOT_FOUND"


@pytest.mark.asyncio
async def test_unauthorized_member_cannot_invite(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that VIEWER and MEMBER roles cannot invite/add new members (requires member:invite)."""
    owner = await _create_user(test_db_session)
    regular_member = await _create_user(test_db_session, "member@corp.internal")
    viewer = await _create_user(test_db_session, "viewer@corp.internal")
    new_user = await _create_user(test_db_session, "new@corp.internal")
    org = await _create_org_with_owner(test_db_session, owner)

    # Add member and viewer
    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(regular_member.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )
    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(viewer.id), "role": OrgRole.VIEWER.value},
        headers=_auth_header(owner),
    )

    # 1. MEMBER attempts to add user -> 403
    res_m = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(new_user.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(regular_member),
    )
    assert res_m.status_code == 403
    assert res_m.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # 2. VIEWER attempts to add user -> 403
    res_v = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(new_user.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(viewer),
    )
    assert res_v.status_code == 403
    assert res_v.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


@pytest.mark.asyncio
async def test_member_operations_on_inactive_organization(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify that all member operations return 403 when the organization is inactive."""
    owner = await _create_user(test_db_session)
    member = await _create_user(test_db_session)
    org = await _create_org_with_owner(test_db_session, owner)

    # Add member while active
    await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(member.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )

    # Deactivate organization
    del_res = await client.delete(
        f"/api/v1/organizations/{org.id}",
        headers=_auth_header(owner),
    )
    assert del_res.status_code == 200

    # 1. GET /members -> 403 ORGANIZATION_INACTIVE
    res_list = await client.get(
        f"/api/v1/organizations/{org.id}/members",
        headers=_auth_header(owner),
    )
    assert res_list.status_code == 403
    assert res_list.json()["error"]["code"] == "ORGANIZATION_INACTIVE"

    # 2. POST /members -> 403 ORGANIZATION_INACTIVE
    another_user = await _create_user(test_db_session)
    await test_db_session.commit()
    res_post = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(another_user.id), "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )
    assert res_post.status_code == 403
    assert res_post.json()["error"]["code"] == "ORGANIZATION_INACTIVE"

    # 3. PATCH /members/{id} -> 403 ORGANIZATION_INACTIVE
    res_patch = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        json={"role": OrgRole.ADMIN.value},
        headers=_auth_header(owner),
    )
    assert res_patch.status_code == 403
    assert res_patch.json()["error"]["code"] == "ORGANIZATION_INACTIVE"

    # 4. DELETE /members/{id} -> 403 ORGANIZATION_INACTIVE
    res_del = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        headers=_auth_header(owner),
    )
    assert res_del.status_code == 403
    assert res_del.json()["error"]["code"] == "ORGANIZATION_INACTIVE"


@pytest.mark.asyncio
async def test_add_member_with_both_user_id_and_email(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify adding member with both matching user_id and email succeeds, but mismatched fails."""
    owner = await _create_user(test_db_session)
    user_a = await _create_user(test_db_session, "user_a@nexus.internal")
    user_b = await _create_user(test_db_session, "user_b@nexus.internal")
    org = await _create_org_with_owner(test_db_session, owner)

    # Matching user_id and email -> 201
    res_match = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(user_a.id), "email": user_a.email, "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )
    assert res_match.status_code == 201
    assert res_match.json()["user_id"] == str(user_a.id)

    # Mismatched user_id and email -> 404 USER_NOT_FOUND
    res_mismatch = await client.post(
        f"/api/v1/organizations/{org.id}/members",
        json={"user_id": str(user_b.id), "email": "wrong_email@nexus.internal", "role": OrgRole.MEMBER.value},
        headers=_auth_header(owner),
    )
    assert res_mismatch.status_code == 404
    assert res_mismatch.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_member_endpoints_unauthenticated(
    client: AsyncClient,
) -> None:
    """Verify that unauthenticated requests to member endpoints return 401."""
    dummy_org = uuid.uuid4()
    dummy_user = uuid.uuid4()

    # GET /members
    res_get = await client.get(f"/api/v1/organizations/{dummy_org}/members")
    assert res_get.status_code == 401

    # POST /members
    res_post = await client.post(
        f"/api/v1/organizations/{dummy_org}/members",
        json={"email": "test@test.com", "role": "MEMBER"},
    )
    assert res_post.status_code == 401

    # PATCH /members/{user_id}
    res_patch = await client.patch(
        f"/api/v1/organizations/{dummy_org}/members/{dummy_user}",
        json={"role": "ADMIN"},
    )
    assert res_patch.status_code == 401

    # DELETE /members/{user_id}
    res_del = await client.delete(f"/api/v1/organizations/{dummy_org}/members/{dummy_user}")
    assert res_del.status_code == 401


@pytest.mark.asyncio
async def test_bind_resolution_and_dialect_detection(
    test_db_session: AsyncSession,
) -> None:
    """Verify that _is_postgresql_session reliably detects dialect via getattr or get_bind."""
    from unittest.mock import MagicMock
    from app.services.membership_service import _is_postgresql_session

    # 1. Real SQLite test session returns False without error
    assert _is_postgresql_session(test_db_session) is False

    # 2. Mock session with bind.dialect.name == "postgresql" returns True
    pg_mock_session = MagicMock()
    pg_mock_session.bind.dialect.name = "postgresql"
    assert _is_postgresql_session(pg_mock_session) is True

    # 3. Mock session with bind=None but get_bind() returning postgresql engine returns True
    fallback_session = MagicMock()
    fallback_session.bind = None
    fallback_bind = MagicMock()
    fallback_bind.dialect.name = "postgresql"
    fallback_session.get_bind.return_value = fallback_bind
    assert _is_postgresql_session(fallback_session) is True

    # 4. Mock session with bind=None and get_bind() raising exception returns False safely
    broken_session = MagicMock()
    broken_session.bind = None
    broken_session.get_bind.side_effect = RuntimeError("No bind available")
    assert _is_postgresql_session(broken_session) is False

