from __future__ import annotations

import math
from typing import TYPE_CHECKING

from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.schemas.forward import (
    ForwardPredictionItem,
    ForwardPredictionRequest,
    ForwardPredictionResponse,
)

if TYPE_CHECKING:
    from app.model_runtime.ensemble import EnsemblePrediction


def _finite(value: float, display_name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{display_name} is not finite")
    return number


def map_prediction_response(
    request: ForwardPredictionRequest,
    prediction: "EnsemblePrediction",
) -> ForwardPredictionResponse:
    try:
        chips = request.chips_by_position()
        seeds = sorted(prediction.seed_predictions)
        items: list[ForwardPredictionItem] = []
        for index, chip in enumerate(chips):
            point = f"y{index + 1}"
            seed_values = {
                str(seed): _finite(prediction.seed_predictions[seed][0, index], f"{point}.seed_{seed}")
                for seed in seeds
            }
            items.append(
                ForwardPredictionItem(
                    position=index + 1,
                    point=point,
                    chip_type=chip.chip_type,
                    mean=_finite(prediction.mean[0, index], f"{point}.mean"),
                    std=_finite(prediction.std[0, index], f"{point}.std"),
                    seed_values=seed_values,
                )
            )

        return ForwardPredictionResponse(
            sample_name=request.sample_name,
            inlets={"inlet1": float(request.inlet1), "inlet2": float(request.inlet2)},
            ensemble_seeds=seeds,
            predictions=items,
        )
    except Exception as exc:
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_OUTPUT_SCHEMA_ERROR,
            "Failed to map forward model output.",
            {"error": str(exc)},
        ) from exc
