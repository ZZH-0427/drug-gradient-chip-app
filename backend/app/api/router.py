from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import chat, forward, health, reverse


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(forward.router)
api_router.include_router(reverse.router)
api_router.include_router(chat.router)
