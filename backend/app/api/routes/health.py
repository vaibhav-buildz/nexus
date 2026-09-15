"""Health and readiness check endpoints."""

import logging
from typing import Any
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import Settings, get_settings
from app.db.session import get_db_session, verify_database_connection

router = APIRouter(tags=["Health"])
logger = logging.getLogger("nexus.health")


@router.get(
    "/health",
    summary="Application liveness check",
    status_code=status.HTTP_200_OK,
    response_model=dict[str, Any],
)
async def health_check(
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Verify that the FastAPI application is alive and accepting requests."""
    return {
        "status": "ok",
        "service": settings.PROJECT_NAME,
        "environment": settings.APP_ENV,
    }


@router.get(
    "/health/db",
    summary="Database readiness probe",
    status_code=status.HTTP_200_OK,
    response_model=dict[str, Any],
    responses={
        200: {"description": "Database is connected and healthy"},
        503: {"description": "Database is unreachable or failed health check"},
    },
)
async def database_health_check(
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Verify that the PostgreSQL database is reachable by executing a test query."""
    try:
        health_info = await verify_database_connection(session)
        return {
            "status": "ok",
            "database": health_info["status"],
            "latency_ms": health_info["latency_ms"],
        }
    except Exception as exc:
        logger.error(
            "Database health check failed: %s",
            str(exc),
            exc_info=True,
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(exc),
        }
