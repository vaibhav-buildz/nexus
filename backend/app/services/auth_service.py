"""Authentication and identity service managing users, sessions, and credentials."""

from datetime import datetime, timedelta, timezone
import logging
import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.errors import (
    EmailVerificationError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenReuseDetectedError,
    UserAlreadyExistsError,
)
from app.core.security import (
    create_access_token,
    generate_secure_random_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.email_verification import EmailVerificationToken
from app.models.session import Session
from app.models.user import User
from app.services.email_service import BaseEmailService

logger = logging.getLogger("nexus.auth")


class AuthService:
    """Core domain service for user registration, authentication, sessions, and token rotation."""

    @staticmethod
    async def register_user(
        db: AsyncSession,
        email: str,
        password: str,
        email_service: BaseEmailService,
    ) -> tuple[User, str]:
        """Register a new user account with Argon2id password hashing and email verification."""
        normalized_email = email.lower().strip()

        # Check existing user
        existing_user = await db.scalar(select(User).where(User.email == normalized_email))
        if existing_user:
            raise UserAlreadyExistsError("A user with this email address already exists.")

        # Create user
        hashed = hash_password(password)
        new_user = User(
            email=normalized_email,
            password_hash=hashed,
            is_active=True,
            is_verified=False,
        )
        db.add(new_user)
        await db.flush()

        # Generate email verification token
        settings = get_settings()
        raw_verification_token = generate_secure_random_token(32)
        verification_hash = hash_token(raw_verification_token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS)

        verification_record = EmailVerificationToken(
            user_id=new_user.id,
            token_hash=verification_hash,
            expires_at=expires_at,
        )
        db.add(verification_record)
        await db.commit()
        await db.refresh(new_user)

        # Dispatch verification email
        await email_service.send_verification_email(new_user.email, raw_verification_token)

        logger.info(
            "User registered successfully",
            extra={"user_id": str(new_user.id), "email": new_user.email},
        )
        return new_user, raw_verification_token

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        email: str,
        password: str,
    ) -> User:
        """Authenticate user credentials using constant-time password verification."""
        normalized_email = email.lower().strip()
        user = await db.scalar(select(User).where(User.email == normalized_email))

        # Always execute password verification (with a dummy hash if user not found)
        # to prevent timing-based user enumeration attacks.
        dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$dummyhashtopreventtimingattacks$dummyhashvaluehere"
        target_hash = user.password_hash if user else dummy_hash
        is_valid = verify_password(password, target_hash)

        if not user or not is_valid:
            logger.warning("Failed login attempt for email: %s", normalized_email)
            raise InvalidCredentialsError("Invalid email or password.")

        if not user.is_active:
            logger.warning("Login attempt for inactive user_id: %s", user.id)
            raise InactiveUserError("User account is inactive. Please contact support.")

        return user

    @staticmethod
    async def create_session(
        db: AsyncSession,
        user: User,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[str, str]:
        """Create a new user session with access token and secure refresh token."""
        settings = get_settings()
        now = datetime.now(timezone.utc)
        family_id = uuid.uuid4()
        raw_refresh_token = generate_secure_random_token(32)
        token_hash = hash_token(raw_refresh_token)
        expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        session_record = Session(
            user_id=user.id,
            family_id=family_id,
            token_hash=token_hash,
            user_agent=user_agent[:500] if user_agent else None,
            ip_address=ip_address[:45] if ip_address else None,
            expires_at=expires_at,
            created_at=now,
            last_used_at=now,
        )
        db.add(session_record)
        await db.commit()

        access_token = create_access_token(subject=str(user.id))
        logger.info("Session created for user_id: %s, family_id: %s", user.id, family_id)
        return access_token, raw_refresh_token

    @staticmethod
    async def refresh_session(
        db: AsyncSession,
        raw_refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[str, str]:
        """Rotate refresh token and detect token reuse attacks."""
        token_hash = hash_token(raw_refresh_token)
        session = await db.scalar(select(Session).where(Session.token_hash == token_hash))

        if not session:
            logger.warning("Refresh attempt with non-existent token hash.")
            raise InvalidTokenError("Invalid or expired refresh token.")

        # REUSE DETECTION: An already revoked token is being presented again!
        if session.is_revoked:
            logger.critical(
                "SECURITY ALERT: Refresh token reuse detected! Family: %s, User: %s",
                session.family_id,
                session.user_id,
            )
            # Revoke all sessions in the entire family immediately
            now = datetime.now(timezone.utc)
            await db.execute(
                update(Session)
                .where(Session.family_id == session.family_id)
                .where(Session.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            await db.commit()
            raise TokenReuseDetectedError(
                "Security alert: Refresh token reuse detected. All related sessions have been invalidated."
            )

        if session.is_expired:
            logger.info("Refresh attempt with expired session: %s", session.id)
            raise InvalidTokenError("Refresh token has expired.")

        user = await db.scalar(select(User).where(User.id == session.user_id))
        if not user or not user.is_active:
            raise InactiveUserError("User account is inactive.")

        # Valid refresh: Rotate token!
        now = datetime.now(timezone.utc)
        settings = get_settings()

        # 1. Revoke the old token
        session.revoked_at = now
        session.last_used_at = now

        # 2. Issue the new token in the same family
        new_raw_refresh = generate_secure_random_token(32)
        new_token_hash = hash_token(new_raw_refresh)
        new_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        new_session = Session(
            user_id=user.id,
            family_id=session.family_id,
            token_hash=new_token_hash,
            user_agent=user_agent[:500] if user_agent else session.user_agent,
            ip_address=ip_address[:45] if ip_address else session.ip_address,
            expires_at=new_expires_at,
            created_at=now,
            last_used_at=now,
        )
        db.add(new_session)
        await db.commit()

        new_access_token = create_access_token(subject=str(user.id))
        logger.info(
            "Refresh token rotated successfully for user_id: %s, family_id: %s",
            user.id,
            session.family_id,
        )
        return new_access_token, new_raw_refresh

    @staticmethod
    async def revoke_session(
        db: AsyncSession,
        raw_refresh_token: str,
    ) -> None:
        """Revoke a session by its refresh token."""
        token_hash = hash_token(raw_refresh_token)
        session = await db.scalar(select(Session).where(Session.token_hash == token_hash))
        if session and not session.is_revoked:
            session.revoked_at = datetime.now(timezone.utc)
            session.last_used_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("Session %s revoked successfully.", session.id)

    @staticmethod
    async def verify_email(
        db: AsyncSession,
        raw_token: str,
    ) -> User:
        """Validate email verification token and activate user verification status."""
        token_hash = hash_token(raw_token)
        record = await db.scalar(
            select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
        )

        if not record or record.is_used or record.is_expired:
            raise EmailVerificationError("Email verification token is invalid or expired.")

        user = await db.scalar(select(User).where(User.id == record.user_id))
        if not user:
            raise EmailVerificationError("Associated user account not found.")

        record.used_at = datetime.now(timezone.utc)
        user.is_verified = True
        await db.commit()
        await db.refresh(user)

        logger.info("Email verified successfully for user_id: %s", user.id)
        return user
