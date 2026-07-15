from __future__ import annotations

import numpy as np
from types import SimpleNamespace

from app.model_runtime.result_mapper import map_prediction_response
from app.schemas.forward import ForwardPredictionRequest


def test_result_mapper_returns_plain_structured_output() -> None:
    request = ForwardPredictionRequest(
        sample_name="DP 0",
        inlet1=1.0,
        inlet2=0.0,
        chips=[
            {
                "position": position,
                "chip_type": f"{position}to{position}",
                "left_width_mm": 0.1,
                "right_width_mm": 0.2,
                "left_bend_straight_distance_mm": 10.0,
                "right_bend_straight_distance_mm": 20.0,
            }
            for position in range(1, 7)
        ],
    )
    prediction = SimpleNamespace(
        mean=np.array([[1, 2, 3, 4, 5, 6]], dtype=np.float64),
        std=np.array([[0.1, 0.2, 0.3, 0.4, 0.5, 0.6]], dtype=np.float64),
        seed_predictions={
            42: np.array([[1, 2, 3, 4, 5, 6]], dtype=np.float64),
            52: np.array([[2, 3, 4, 5, 6, 7]], dtype=np.float64),
        },
    )

    response = map_prediction_response(request, prediction)
    payload = response.model_dump()

    assert payload["sample_name"] == "DP 0"
    assert payload["ensemble_seeds"] == [42, 52]
    assert len(payload["predictions"]) == 6
    assert payload["predictions"][0] == {
        "position": 1,
        "point": "y1",
        "chip_type": "1to1",
        "mean": 1.0,
        "std": 0.1,
        "seed_values": {"42": 1.0, "52": 2.0},
    }
