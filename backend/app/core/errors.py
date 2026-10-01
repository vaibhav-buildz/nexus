"""Global error handling and exception classes for NEXUS."""

import logging
from typing import Any
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("nexus.errors")


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "INTERNAL_ERROR",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details


class DatabaseConnectionError(AppException):
    """Raised when the database cannot be reached."""

    def __init__(self, message: str = "Database connection failed", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="DATABASE_UNAVAILABLE",
            details=details,
        )


class InvalidCredentialsError(AppException):
    """Raised when email/password verification fails."""

    def __init__(self, message: str = "Invalid email or password.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CREDENTIALS",
            details=details,
        )


class InvalidTokenError(AppException):
    """Raised when an access or refresh token is invalid, expired, or revoked."""

    def __init__(self, message: str = "Token is invalid or expired.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_TOKEN",
            details=details,
        )


class TokenReuseDetectedError(AppException):
    """Raised when a previously rotated or revoked refresh token is reused."""

    def __init__(
        self,
        message: str = "Security alert: Refresh token reuse detected. All related sessions have been revoked.",
        details: Any = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="TOKEN_REUSE_DETECTED",
            details=details,
        )


class InactiveUserError(AppException):
    """Raised when an inactive/disabled user attempts an action."""

    def __init__(self, message: str = "User account is inactive.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="USER_INACTIVE",
            details=details,
        )


class UserAlreadyExistsError(AppException):
    """Raised when registration email is already in use."""

    def __init__(self, message: str = "A user with this email already exists.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code="USER_ALREADY_EXISTS",
            details=details,
        )


class EmailVerificationError(AppException):
    """Raised when email verification token is invalid, expired, or already used."""

    def __init__(self, message: str = "Invalid or expired email verification token.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="EMAIL_VERIFICATION_FAILED",
            details=details,
        )


class OrganizationNotFoundError(AppException):
    """Raised when an organization is not found by ID or slug."""

    def __init__(self, message: str = "Organization not found.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code="ORGANIZATION_NOT_FOUND",
            details=details,
        )


class OrganizationAlreadyExistsError(AppException):
    """Raised when an organization with the same slug already exists."""

    def __init__(self, message: str = "An organization with this slug already exists.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code="ORGANIZATION_ALREADY_EXISTS",
            details=details,
        )


class InactiveOrganizationError(AppException):
    """Raised when an action is attempted on an inactive organization."""

    def __init__(self, message: str = "Organization is inactive.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="ORGANIZATION_INACTIVE",
            details=details,
        )


class NotAnOrganizationMemberError(AppException):
    """Raised when a user is not a member of the target organization."""

    def __init__(self, message: str = "Not a member of this organization.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="NOT_AN_ORG_MEMBER",
            details=details,
        )


class MemberAlreadyExistsError(AppException):
    """Raised when a user is already a member of the organization."""

    def __init__(self, message: str = "User is already a member of this organization.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code="MEMBER_ALREADY_EXISTS",
            details=details,
        )


class MemberNotFoundError(AppException):
    """Raised when a member is not found in the organization."""

    def __init__(self, message: str = "Member not found in this organization.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code="MEMBER_NOT_FOUND",
            details=details,
        )


class UserNotFoundError(AppException):
    """Raised when a specified user does not exist."""

    def __init__(self, message: str = "User not found.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code="USER_NOT_FOUND",
            details=details,
        )


class InsufficientPermissionsError(AppException):
    """Raised when an actor lacks the required RBAC permission."""

    def __init__(self, message: str = "Insufficient permissions.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="INSUFFICIENT_PERMISSIONS",
            details=details,
        )


class GovernanceRuleViolationError(AppException):
    """Raised when an operation violates organization governance/RBAC policy."""

    def __init__(self, message: str = "Insufficient permissions.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="GOVERNANCE_RULE_VIOLATION",
            details=details,
        )


class ProjectNotFoundError(AppException):
    """Raised when a project is not found within the organization context."""

    def __init__(self, message: str = "Project not found.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code="PROJECT_NOT_FOUND",
            details=details,
        )


class ProjectAlreadyExistsError(AppException):
    """Raised when a project with the same slug already exists in the organization."""

    def __init__(
        self,
        message: str = "A project with this slug already exists in this organization.",
        details: Any = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code="PROJECT_ALREADY_EXISTS",
            details=details,
        )


class InactiveProjectError(AppException):
    """Raised when an update operation is attempted on an inactive project."""

    def __init__(self, message: str = "Cannot update an inactive project.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="PROJECT_INACTIVE",
            details=details,
        )


class EnvironmentNotFoundError(AppException):
    """Raised when an environment is not found within the organization and project context."""

    def __init__(self, message: str = "Environment not found.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code="ENVIRONMENT_NOT_FOUND",
            details=details,
        )


class EnvironmentAlreadyExistsError(AppException):
    """Raised when an environment with the same slug already exists in the project."""

    def __init__(
        self,
        message: str = "An environment with this slug already exists in this project.",
        details: Any = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code="ENVIRONMENT_ALREADY_EXISTS",
            details=details,
        )


class InactiveEnvironmentError(AppException):
    """Raised when an update operation is attempted on an inactive environment."""

    def __init__(self, message: str = "Cannot update an inactive environment.", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="ENVIRONMENT_INACTIVE",
            details=details,
        )


def create_error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    """Helper to return consistent JSON error envelopes."""
    payload = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


def register_error_handlers(app: FastAPI) -> None:
    """Register all global exception handlers on the FastAPI app."""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "Application exception: %s",
            exc.message,
            extra={"path": request.url.path, "code": exc.code, "details": exc.details},
        )
        return create_error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        logger.warning(
            "HTTP exception %d: %s",
            exc.status_code,
            exc.detail,
            extra={"path": request.url.path, "status_code": exc.status_code},
        )
        code = "HTTP_ERROR"
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            code = "NOT_FOUND"
        elif exc.status_code == status.HTTP_400_BAD_REQUEST:
            code = "BAD_REQUEST"
        elif exc.status_code == status.HTTP_403_FORBIDDEN:
            code = "FORBIDDEN"

        return create_error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        clean_errors = [
            {
                "type": str(e.get("type", "")),
                "loc": [str(x) for x in e.get("loc", [])],
                "msg": str(e.get("msg", "")),
            }
            for e in exc.errors()
        ]
        logger.warning(
            "Request validation error on %s",
            request.url.path,
            extra={"path": request.url.path, "errors": clean_errors},
        )
        return create_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="VALIDATION_ERROR",
            message="Invalid request payload or parameters",
            details=clean_errors,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled server error: %s",
            str(exc),
            extra={"path": request.url.path},
        )
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred.",
        )
