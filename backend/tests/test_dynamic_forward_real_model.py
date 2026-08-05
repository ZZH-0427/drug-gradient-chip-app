from __future__ import annotations

import math
import os
from copy import deepcopy

import pytest

from app.core.config import ForwardModelSettings
from app.model_runtime.forward_adapter import ForwardModelAdapter
from app.schemas.forward import ForwardPredictionRequest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SLOW_MODEL_TESTS") != "1",
    reason="Set RUN_SLOW_MODEL_TESTS=1 to run real dynamic model tests.",
)


def make_payload(chip_count: int) -> dict[str, object]:
    chip_types = ["5to4", "4to2", "1to6", "2to4", "6to3", "3to1", "1to1", "2to2", "3to3", "4to4"]
    return {
        "sample_name": f"slow-{chip_count}",
        "chip_count": chip_count,
        "inlet1": 1.0,
        "inlet2": 0.0,
        "chips": [
            {
                "position": position,
                "chip_type": chip_types[position - 1],
                "left_width_mm": round(0.05 + 0.01 * position, 3),
                "right_width_mm": round(0.06 + 0.01 * position, 3),
                "left_bend_straight_distance_mm": 10.0 + position,
                "right_bend_straight_distance_mm": 20.0 + position,
            }
            for position in range(1, chip_count + 1)
        ],
    }


@pytest.fixture(scope="module")
def adapter() -> ForwardModelAdapter:
    settings = ForwardModelSettings.from_env()
    return ForwardModelAdapter(settings)


@pytest.mark.parametrize("chip_count", [4, 5, 6, 7, 8, 9, 10])
def test_real_dynamic_forward_outputs_concentration_only(adapter: ForwardModelAdapter, chip_count: int) -> None:
    response = adapter.predict(ForwardPredictionRequest(**make_payload(chip_count)))

    assert response.chip_count == chip_count
    assert len(response.predictions) == chip_count
    for index, prediction in enumerate(response.predictions, start=1):
        assert prediction.position == index
        assert prediction.point == f"y{index}"
        assert math.isfinite(prediction.concentration)
        assert not hasattr(prediction, "flow")
        assert not hasattr(prediction, "seed_values")


@pytest.mark.parametrize("chip_count", [9, 10])
def test_real_dynamic_forward_tail_chip_affects_output(adapter: ForwardModelAdapter, chip_count: int) -> None:
    base_payload = make_payload(chip_count)
    changed_payload = deepcopy(base_payload)
    tail = changed_payload["chips"][-1]
    tail["left_width_mm"] = 0.31
    tail["right_width_mm"] = 0.04

    base = adapter.predict(ForwardPredictionRequest(**base_payload))
    changed = adapter.predict(ForwardPredictionRequest(**changed_payload))

    assert abs(base.predictions[-1].concentration - changed.predictions[-1].concentration) > 1e-8
