from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from app.core.config import ForwardModelSettings
from app.model_runtime.input_parser import parse_forward_csv

pytest.importorskip("torch")
pytest.importorskip("torch_geometric")

from app.model_runtime.forward_adapter import ForwardModelAdapter


def _float(row: dict[str, str], key: str) -> float:
    return float(row[key])


@pytest.mark.skipif(
    not os.getenv("MODEL_SOURCE_ROOT"),
    reason="MODEL_SOURCE_ROOT is not configured; skipping real checkpoint golden test.",
)
def test_golden_forward_prediction_matches_source_csv() -> None:
    settings = ForwardModelSettings.from_env()
    adapter = ForwardModelAdapter(settings)

    requests = parse_forward_csv(settings.golden_input_path)
    assert requests
    response = adapter.predict(requests[0])

    with Path(settings.golden_output_path).open(newline="", encoding="utf-8-sig") as handle:
        expected = next(csv.DictReader(handle))

    assert response.sample_name == expected["sample_name"]
    assert response.inlets == {
        "inlet1": _float(expected, "inlet1"),
        "inlet2": _float(expected, "inlet2"),
    }
    assert response.ensemble_seeds == [42, 52, 62, 72, 82]

    for prediction in response.predictions:
        point = prediction.point
        chip = prediction.chip_type
        assert expected[f"{point}_chip_name"] == chip
        assert abs(prediction.mean - _float(expected, f"{point}_{chip}_pred_mean")) <= 1e-6
        assert abs(prediction.std - _float(expected, f"{point}_{chip}_pred_std")) <= 1e-6
        for seed, value in prediction.seed_values.items():
            assert abs(value - _float(expected, f"{point}_{chip}_seed_{seed}")) <= 1e-6
