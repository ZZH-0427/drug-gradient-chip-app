from __future__ import annotations

from fastapi import Request

from app.core.model_state import ForwardModelState


def get_forward_model_state(request: Request) -> ForwardModelState:
    state = getattr(request.app.state, "forward_model", None)
    if isinstance(state, ForwardModelState):
        return state
    return ForwardModelState.not_ready(
        code="MODEL_NOT_READY",
        message="Forward model state has not been initialized.",
    )
