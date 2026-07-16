from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import forward, health


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(forward.router)
