from __future__ import annotations

import numpy as np
from types import SimpleNamespace

import pytest

pytest.importorskip("torch")

from app.model_runtime.forward_adapter import ForwardModelRouter
from app.model_runtime.result_mapper import map_prediction_response
from app.schemas.forward import ForwardPredictionRequest


class _RuntimeSpy:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[int] = []

    def predict(self, request: ForwardPredictionRequest) -> str:
        self.calls.append(request.chip_count)
        return self.name


def _request_with_chip_count(chip_count: int) -> ForwardPredictionRequest:
    return ForwardPredictionRequest(
        sample_name=f"DP {chip_count}",
        chip_count=chip_count,
        inlet1=1.0,
        inlet2=0.0,
        chips=[
            {
                "position": position,
                "chip_type": f"{min(position, 6)}to{min(position, 6)}",
                "left_width_mm": 0.1,
                "right_width_mm": 0.2,
                "left_bend_straight_distance_mm": 10.0,
                "right_bend_straight_distance_mm": 20.0,
            }
            for position in range(1, chip_count + 1)
        ],
    )


@pytest.mark.parametrize("chip_count", [4, 5, 7, 8, 9, 10])
def test_forward_router_sends_non_six_counts_to_zero_shot_runtime(chip_count: int) -> None:
    fixed = _RuntimeSpy("fixed")
    zero_shot = _RuntimeSpy("zero-shot")
    router = ForwardModelRouter(fixed_six=fixed, zero_shot=zero_shot)

    result = router.predict(_request_with_chip_count(chip_count))

    assert result == "zero-shot"
    assert fixed.calls == []
    assert zero_shot.calls == [chip_count]


def test_forward_router_sends_six_count_to_fixed_runtime() -> None:
    fixed = _RuntimeSpy("fixed")
    zero_shot = _RuntimeSpy("zero-shot")
    router = ForwardModelRouter(fixed_six=fixed, zero_shot=zero_shot)

    result = router.predict(_request_with_chip_count(6))

    assert result == "fixed"
    assert fixed.calls == [6]
    assert zero_shot.calls == []


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
    prediction = np.array([[1, 2, 3, 4, 5, 6]], dtype=np.float64)

    response = map_prediction_response(request, prediction)
    payload = response.model_dump()

    assert payload["sample_name"] == "DP 0"
    assert payload["chip_count"] == 6
    assert len(payload["predictions"]) == 6
    assert payload["predictions"][0] == {
        "position": 1,
        "point": "y1",
        "chip_type": "1to1",
        "concentration": 1.0,
    }
