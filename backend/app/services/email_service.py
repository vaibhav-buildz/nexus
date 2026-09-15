"""Email delivery service abstraction supporting local, testing, and production backends."""

from abc import ABC, abstractmethod
import logging
from app.core.config import get_settings

logger = logging.getLogger("nexus.email")


class BaseEmailService(ABC):
    """Abstract contract for sending platform emails."""

    @abstractmethod
    async def send_verification_email(self, email: str, verification_token: str) -> None:
        """Deliver email verification link/token to user."""
        pass


class ConsoleEmailService(BaseEmailService):
    """Development email backend that logs verification tokens to the console/logger."""

    async def send_verification_email(self, email: str, verification_token: str) -> None:
        logger.info(
            "[DEV EMAIL] Verification email dispatched to %s",
            email,
            extra={
                "recipient": email,
                "verification_token": verification_token,
                "action_url": f"/api/v1/auth/verify-email?token={verification_token}",
            },
        )


class MockEmailService(BaseEmailService):
    """In-memory testing email backend that records sent emails."""

    def __init__(self) -> None:
        self.sent_emails: list[dict[str, str]] = []

    async def send_verification_email(self, email: str, verification_token: str) -> None:
        self.sent_emails.append({
            "email": email,
            "verification_token": verification_token,
        })


def get_email_service() -> BaseEmailService:
    """Dependency / factory returning configured email service provider."""
    settings = get_settings()
    if settings.EMAIL_SERVICE_PROVIDER == "mock" or settings.APP_ENV == "testing":
        return MockEmailService()
    return ConsoleEmailService()
