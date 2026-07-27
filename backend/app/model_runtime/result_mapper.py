from __future__ import annotations

import math
import numpy as np

from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.schemas.forward import (
    ForwardPredictionItem,
    ForwardPredictionRequest,
    ForwardPredictionResponse,
)

def _finite(value: float, display_name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{display_name} is not finite")
    return number


def map_prediction_response(
    request: ForwardPredictionRequest,
    prediction: np.ndarray,
) -> ForwardPredictionResponse:
    try:
        chips = request.chips_by_position()
        items: list[ForwardPredictionItem] = []
        for index, chip in enumerate(chips):
            point = f"y{index + 1}"
            items.append(
                ForwardPredictionItem(
                    position=index + 1,
                    point=point,
                    chip_type=chip.chip_type,
                    concentration=_finite(prediction[0, index], f"{point}.concentration"),
                )
            )

        return ForwardPredictionResponse(
            sample_name=request.sample_name,
            inlets={"inlet1": float(request.inlet1), "inlet2": float(request.inlet2)},
            chip_count=request.chip_count,
            predictions=items,
        )
    except Exception as exc:
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
            "Failed to map forward model output.",
            {"error": str(exc)},
        ) from exc
