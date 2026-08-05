from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import get_forward_model_state
from app.core.model_state import (
    FORWARD_SUPPORTED_CHIP_COUNTS,
    REVERSE_SUPPORTED_CHIP_COUNTS,
    ForwardModelState,
)
from app.schemas.common import ErrorResponse, HealthResponse, ModelStatusResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="drug-gradient-chip-api")


@router.get(
    "/model-status",
    response_model=ModelStatusResponse,
    responses={503: {"model": ErrorResponse}},
)
def model_status(
    model_state: ForwardModelState = Depends(get_forward_model_state),
) -> ModelStatusResponse:
    if not model_state.ready:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": model_state.error_code or "MODEL_NOT_READY",
                    "message": model_state.error_message or "Forward model is not ready.",
                }
            },
        )

    return ModelStatusResponse(
        ready=True,
        model_name=model_state.model_name,
        supported_chip_counts=model_state.supported_chip_counts or FORWARD_SUPPORTED_CHIP_COUNTS,
        public_output=model_state.public_output,
        device=model_state.device,
        forward={
            "ready": True,
            "supported_chip_counts": FORWARD_SUPPORTED_CHIP_COUNTS,
            "output": "concentration",
            "execution_mode": "sync",
        },
        reverse={
            "ready": True,
            "supported_chip_counts": REVERSE_SUPPORTED_CHIP_COUNTS,
            "execution_mode": "async",
            "max_concurrent_tasks": 1,
        },
    )
