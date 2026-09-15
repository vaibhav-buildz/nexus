"""Comprehensive PostgreSQL integration tests for authentication and identity."""

from datetime import datetime, timedelta, timezone
import uuid
from httpx import AsyncClient
import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.security import create_access_token, hash_token
from app.models.email_verification import EmailVerificationToken
from app.models.session import Session
from app.models.user import User


# ==============================================================================
# 1. REGISTRATION TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_registration_success(client: AsyncClient, test_db_session: AsyncSession) -> None:
    """Verify successful user registration with Argon2id hash and email token."""
    payload = {
        "email": "engineer@nexus.internal",
        "password": "SecurePassword123!",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["email"] == "engineer@nexus.internal"
    assert data["is_active"] is True
    assert data["is_verified"] is False
    assert "id" in data

    # Verify database persistence
    user = await test_db_session.scalar(
        select(User).where(User.email == "engineer@nexus.internal")
    )
    assert user is not None
    # Password must NEVER be plaintext
    assert user.password_hash != "SecurePassword123!"
    assert user.password_hash.startswith("$argon2id$")

    # Verify email verification token was recorded
    token_rec = await test_db_session.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
    )
    assert token_rec is not None
    assert token_rec.is_used is False


@pytest.mark.asyncio
async def test_registration_duplicate_email(client: AsyncClient) -> None:
    """Verify duplicate email registration returns 409 Conflict."""
    payload = {"email": "duplicate@nexus.internal", "password": "Password123"}
    resp1 = await client.post("/api/v1/auth/register", json=payload)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/v1/auth/register", json=payload)
    assert resp2.status_code == 409
    error = resp2.json()["error"]
    assert error["code"] == "USER_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_registration_invalid_email(client: AsyncClient) -> None:
    """Verify invalid email format returns 422 Validation Error."""
    payload = {"email": "not-a-valid-email", "password": "Password123"}
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_registration_weak_password(client: AsyncClient) -> None:
    """Verify weak password without numbers or too short returns 422."""
    # Too short (< 8 chars)
    resp1 = await client.post(
        "/api/v1/auth/register", json={"email": "u1@test.com", "password": "short"}
    )
    assert resp1.status_code == 422

    # No digits
    resp2 = await client.post(
        "/api/v1/auth/register", json={"email": "u2@test.com", "password": "onlylettershere"}
    )
    assert resp2.status_code == 422


# ==============================================================================
# 2. LOGIN TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_db_session: AsyncSession) -> None:
    """Verify successful login returns valid tokens and records active session."""
    reg_payload = {"email": "ops@nexus.internal", "password": "SecurePassword123"}
    await client.post("/api/v1/auth/register", json=reg_payload)

    login_payload = {"email": "ops@nexus.internal", "password": "SecurePassword123"}
    response = await client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200

    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0

    # Verify session persisted in DB with hashed token representation
    refresh_hash = hash_token(data["refresh_token"])
    session = await test_db_session.scalar(
        select(Session).where(Session.token_hash == refresh_hash)
    )
    assert session is not None
    assert session.is_valid is True


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    """Verify wrong password returns 401 with generic message."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "auth_test@nexus.internal", "password": "CorrectPassword123"},
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "auth_test@nexus.internal", "password": "WrongPassword999"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_unknown_user(client: AsyncClient) -> None:
    """Verify unknown user returns generic 401 (preventing user enumeration)."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@nexus.internal", "password": "SomePassword123"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, test_db_session: AsyncSession) -> None:
    """Verify disabled/inactive user cannot log in."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "inactive@nexus.internal", "password": "Password123"},
    )
    # Deactivate user
    user = await test_db_session.scalar(
        select(User).where(User.email == "inactive@nexus.internal")
    )
    user.is_active = False
    await test_db_session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@nexus.internal", "password": "Password123"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "USER_INACTIVE"


# ==============================================================================
# 3. ACCESS TOKEN TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_access_token_validation(client: AsyncClient) -> None:
    """Verify valid token grants access to protected endpoint."""
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "profile@nexus.internal", "password": "Password123"},
    )
    user_id = reg.json()["id"]

    token = create_access_token(subject=user_id)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "profile@nexus.internal"


@pytest.mark.asyncio
async def test_access_token_expired(client: AsyncClient) -> None:
    """Verify expired token returns 401 Unauthorized."""
    user_id = str(uuid.uuid4())
    # Create expired token
    expired_token = create_access_token(
        subject=user_id, expires_delta=timedelta(seconds=-10)
    )
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_access_token_invalid_signature(client: AsyncClient) -> None:
    """Verify token signed with wrong key returns 401 Unauthorized."""
    settings = get_settings()
    tampered_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()), "type": "access", "iss": settings.PROJECT_NAME, "iat": int(datetime.now(timezone.utc).timestamp())},
        "wrong-secret-key-that-does-not-match",
        algorithm="HS256",
    )
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_access_token_malformed(client: AsyncClient) -> None:
    """Verify malformed authorization headers return 401."""
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-valid-jwt-token"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


# ==============================================================================
# 4. REFRESH TOKEN ROTATION & REUSE DETECTION
# ==============================================================================


@pytest.mark.asyncio
async def test_refresh_token_rotation_success(
    client: AsyncClient, test_db_session: AsyncSession
) -> None:
    """Verify refresh token rotation issues a new token pair and revokes the old token."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "rotate@nexus.internal", "password": "Password123"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "rotate@nexus.internal", "password": "Password123"},
    )
    old_refresh_token = login_resp.json()["refresh_token"]

    # Refresh
    refresh_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh_token}
    )
    assert refresh_resp.status_code == 200

    new_refresh_token = refresh_resp.json()["refresh_token"]
    assert new_refresh_token != old_refresh_token

    # Verify old token session in DB is now revoked
    old_hash = hash_token(old_refresh_token)
    old_session = await test_db_session.scalar(
        select(Session).where(Session.token_hash == old_hash)
    )
    assert old_session.is_revoked is True

    # Verify new session is valid with identical family_id
    new_hash = hash_token(new_refresh_token)
    new_session = await test_db_session.scalar(
        select(Session).where(Session.token_hash == new_hash)
    )
    assert new_session.is_valid is True
    assert new_session.family_id == old_session.family_id


@pytest.mark.asyncio
async def test_refresh_token_reuse_detection(
    client: AsyncClient, test_db_session: AsyncSession
) -> None:
    """CRITICAL SECURITY TEST: Submitting an already-rotated token revokes all sessions in family."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "victim@nexus.internal", "password": "Password123"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "victim@nexus.internal", "password": "Password123"},
    )
    token_v1 = login_resp.json()["refresh_token"]

    # Legitimate user rotates token_v1 -> gets token_v2
    rotate_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token_v1})
    token_v2 = rotate_resp.json()["refresh_token"]

    # ATTACKER REUSE: Attacker attempts to use token_v1 again!
    reuse_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token_v1})
    assert reuse_resp.status_code == 401
    assert reuse_resp.json()["error"]["code"] == "TOKEN_REUSE_DETECTED"

    # Verify that token_v2 (and all sessions in family) was immediately revoked!
    v2_hash = hash_token(token_v2)
    session_v2 = await test_db_session.scalar(
        select(Session).where(Session.token_hash == v2_hash)
    )
    assert session_v2.is_revoked is True

    # Attempting to use token_v2 should now also fail
    v2_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token_v2})
    assert v2_resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_expired(
    client: AsyncClient, test_db_session: AsyncSession
) -> None:
    """Verify expired refresh token cannot be refreshed."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "expired@nexus.internal", "password": "Password123"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "expired@nexus.internal", "password": "Password123"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    # Set expiry to the past in DB
    token_h = hash_token(refresh_token)
    session = await test_db_session.scalar(select(Session).where(Session.token_hash == token_h))
    session.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await test_db_session.commit()

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


# ==============================================================================
# 5. LOGOUT TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_logout_revokes_session(
    client: AsyncClient, test_db_session: AsyncSession
) -> None:
    """Verify logout revokes the session and prevents further refresh."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "logout@nexus.internal", "password": "Password123"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "logout@nexus.internal", "password": "Password123"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    logout_resp = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_resp.status_code == 200

    # Verify session in DB is marked revoked
    th = hash_token(refresh_token)
    session = await test_db_session.scalar(select(Session).where(Session.token_hash == th))
    assert session.is_revoked is True

    # Refresh must now trigger reuse detection / be rejected
    refresh_after_logout = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_after_logout.status_code == 401


# ==============================================================================
# 6. PROTECTED ENDPOINT TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_protected_endpoint_without_auth(client: AsyncClient) -> None:
    """Verify missing authorization header returns 401."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_inactive_user(
    client: AsyncClient, test_db_session: AsyncSession
) -> None:
    """Verify inactive user cannot access protected endpoints even with valid token."""
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "deactivated@nexus.internal", "password": "Password123"},
    )
    user_id = reg.json()["id"]

    # Deactivate user
    user = await test_db_session.scalar(select(User).where(User.id == uuid.UUID(user_id)))
    user.is_active = False
    await test_db_session.commit()

    token = create_access_token(subject=user_id)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "USER_INACTIVE"


# ==============================================================================
# 7. EMAIL VERIFICATION TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_email_verification_success(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify valid email verification token activates user verification status."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "verify_me@nexus.internal", "password": "Password123"},
    )
    user = await test_db_session.scalar(
        select(User).where(User.email == "verify_me@nexus.internal")
    )
    assert user.is_verified is False

    token_rec = await test_db_session.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
    )

    # In tests, simulate finding the token or create a known one
    known_token = "valid_test_verification_token_123"
    token_rec.token_hash = hash_token(known_token)
    await test_db_session.commit()

    response = await client.post("/api/v1/auth/verify-email", json={"token": known_token})
    assert response.status_code == 200
    assert response.json()["message"] == "Email address verified successfully."

    # Verify user state updated in DB
    await test_db_session.refresh(user)
    assert user.is_verified is True


@pytest.mark.asyncio
async def test_email_verification_expired(
    client: AsyncClient,
    test_db_session: AsyncSession,
) -> None:
    """Verify expired email verification token returns 400."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "expired_email@nexus.internal", "password": "Password123"},
    )
    user = await test_db_session.scalar(
        select(User).where(User.email == "expired_email@nexus.internal")
    )
    token_rec = await test_db_session.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
    )
    known_token = "expired_token_abc"
    token_rec.token_hash = hash_token(known_token)
    token_rec.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await test_db_session.commit()

    response = await client.post("/api/v1/auth/verify-email", json={"token": known_token})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMAIL_VERIFICATION_FAILED"


@pytest.mark.asyncio
async def test_email_verification_invalid(client: AsyncClient) -> None:
    """Verify completely invalid/tampered token returns 400."""
    response = await client.post(
        "/api/v1/auth/verify-email", json={"token": "completely_fake_token_value"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMAIL_VERIFICATION_FAILED"
