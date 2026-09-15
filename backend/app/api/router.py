"""Main API router combining sub-routers."""

from fastapi import APIRouter
from app.api.routes import health

api_router = APIRouter()

# Mount health routes at root level for load balancer / container orchestrator conventions
api_router.include_router(health.router)
