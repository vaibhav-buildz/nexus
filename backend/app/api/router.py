"""Main API router combining sub-routers."""

from fastapi import APIRouter
from app.api.routes import auth, health

api_router = APIRouter()

# Mount health routes at root level for load balancer / container orchestrator conventions
api_router.include_router(health.router)

# Mount authentication routes
api_router.include_router(auth.router, prefix="/api/v1/auth")
