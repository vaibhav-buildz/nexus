"""Authentication API route handlers."""

from typing import Annotated
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.auth import (
    MessageResponse,
    TokenLogoutRequest,
    TokenRefreshRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    VerifyEmailRequest,
)
from app.services.auth_service import AuthService
from app.services.email_service import BaseEmailService, get_email_service

router = APIRouter(tags=["Authentication"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    summary="Register a new user account",
)
async def register(
    payload: UserRegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    email_service: Annotated[BaseEmailService, Depends(get_email_service)],
) -> UserResponse:
    """Create a new user with Argon2id password hash and dispatch email verification."""
    user, _ = await AuthService.register_user(
        db=db,
        email=payload.email,
        password=payload.password,
        email_service=email_service,
    )
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
    summary="Authenticate and receive access & refresh tokens",
)
async def login(
    payload: UserLoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    """Authenticate user credentials and create an authenticated session."""
    user = await AuthService.authenticate_user(
        db=db,
        email=payload.email,
        password=payload.password,
    )

    user_agent = request.headers.get("user-agent")
    client_ip = request.client.host if request.client else None

    access_token, refresh_token = await AuthService.create_session(
        db=db,
        user=user,
        user_agent=user_agent,
        ip_address=client_ip,
    )

    settings = get_settings()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=TokenResponse,
    summary="Rotate refresh token and obtain new access token",
)
async def refresh(
    payload: TokenRefreshRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    """Rotate an active refresh token with reuse detection."""
    user_agent = request.headers.get("user-agent")
    client_ip = request.client.host if request.client else None

    access_token, new_refresh_token = await AuthService.refresh_session(
        db=db,
        raw_refresh_token=payload.refresh_token,
        user_agent=user_agent,
        ip_address=client_ip,
    )

    settings = get_settings()
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponse,
    summary="Revoke session and invalidate refresh token",
)
async def logout(
    payload: TokenLogoutRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MessageResponse:
    """Revoke an active refresh token session."""
    await AuthService.revoke_session(
        db=db,
        raw_refresh_token=payload.refresh_token,
    )
    return MessageResponse(message="Session successfully logged out.")


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=UserResponse,
    summary="Retrieve authenticated current user profile",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Protected endpoint verifying current authenticated user identity."""
    return UserResponse.model_validate(current_user)


@router.post(
    "/verify-email",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponse,
    summary="Verify user email address using verification token",
)
async def verify_email(
    payload: VerifyEmailRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MessageResponse:
    """Confirm user email address via one-time verification token."""
    await AuthService.verify_email(
        db=db,
        raw_token=payload.token,
    )
    return MessageResponse(message="Email address verified successfully.")
