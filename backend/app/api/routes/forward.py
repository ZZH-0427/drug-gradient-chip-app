from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import get_forward_model_state
from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.core.model_state import ForwardModelState
from app.schemas.common import ErrorResponse
from app.schemas.forward import ForwardPredictionRequest, ForwardPredictionResponse


logger = logging.getLogger(__name__)
router = APIRouter(tags=["forward"])


@router.post(
    "/forward",
    response_model=ForwardPredictionResponse,
    responses={
        422: {"description": "Validation error"},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def predict_forward(
    request: ForwardPredictionRequest,
    model_state: ForwardModelState = Depends(get_forward_model_state),
) -> ForwardPredictionResponse:
    if not model_state.ready or model_state.adapter is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": model_state.error_code or "MODEL_NOT_READY",
                    "message": model_state.error_message or "Forward model is not ready.",
                }
            },
        )

    try:
        return model_state.adapter.predict(request)
    except ModelRuntimeError as exc:
        status_code, code = _map_model_error(exc)
        if status_code >= 500:
            logger.exception("Forward prediction failed: %s", exc)
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": code, "message": exc.message}},
        )
    except Exception as exc:
        logger.exception("Unexpected forward prediction failure")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "FORWARD_INFERENCE_ERROR",
                    "message": "Forward prediction failed.",
                }
            },
        )


def _map_model_error(exc: ModelRuntimeError) -> tuple[int, str]:
    if exc.code == ModelErrorCode.MODEL_INPUT_SCHEMA_ERROR:
        return 422, "FORWARD_INPUT_ERROR"
    if exc.code == ModelErrorCode.MODEL_INFERENCE_FAILED:
        return 500, "FORWARD_INFERENCE_ERROR"
    if exc.code in {
        ModelErrorCode.MODEL_SOURCE_ROOT_MISSING,
        ModelErrorCode.MODEL_ASSET_NOT_FOUND,
        ModelErrorCode.MODEL_CHECKPOINT_INVALID,
        ModelErrorCode.MODEL_CONFIGURATION_ERROR,
    }:
        return 503, "MODEL_CONFIGURATION_ERROR"
    return 500, "FORWARD_INFERENCE_ERROR"
