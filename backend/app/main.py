"""FastAPI application factory and lifecycle entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging
from app.db.session import close_engine, get_engine

logger = logging.getLogger("nexus.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown events cleanly."""
    # 1. Startup phase
    setup_logging()
    settings = get_settings()
    logger.info(
        "Starting %s in %s mode (v0.1.0)",
        settings.PROJECT_NAME,
        settings.APP_ENV,
        extra={"environment": settings.APP_ENV, "debug": settings.DEBUG},
    )

    # Initialize DB engine connection pool
    try:
        get_engine()
    except Exception as exc:
        logger.error("Failed to initialize database engine on startup: %s", exc)

    yield

    # 2. Shutdown phase
    logger.info("Shutting down %s...", settings.PROJECT_NAME)
    await close_engine()
    logger.info("%s shutdown complete.", settings.PROJECT_NAME)


def create_application() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title=f"{settings.PROJECT_NAME} API",
        description="Production Reliability and Recovery Platform API",
        version="0.1.0",
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url="/redoc" if settings.APP_ENV != "production" else None,
        openapi_url="/openapi.json" if settings.APP_ENV != "production" else None,
        lifespan=lifespan,
    )

    # Register global exception handlers
    register_error_handlers(app)

    # Include API routers
    app.include_router(api_router)

    return app


app = create_application()
