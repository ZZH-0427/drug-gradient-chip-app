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


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "forward"
GOLDEN_INPUT = FIXTURE_DIR / "forward_prediction_input.csv"
GOLDEN_EXPECTED = FIXTURE_DIR / "forward_prediction_expected.csv"


def _float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def test_golden_forward_prediction_matches_source_csv() -> None:
    settings = ForwardModelSettings.from_env()
    adapter = ForwardModelAdapter(settings)

    requests = parse_forward_csv(GOLDEN_INPUT)
    assert requests
    response = adapter.predict(requests[0])

    with GOLDEN_EXPECTED.open(newline="", encoding="utf-8-sig") as handle:
        expected = next(csv.DictReader(handle))

    assert response.sample_name == expected["sample_name"]
    assert response.inlets == {
        "inlet1": _float(expected, "inlet1"),
        "inlet2": _float(expected, "inlet2"),
    }
    assert response.chip_count == 6
    for prediction in response.predictions:
        point = prediction.point
        chip = prediction.chip_type
        assert expected[f"{point}_chip_name"] == chip
        assert abs(prediction.concentration - _float(expected, f"{point}_concentration")) <= 1e-6


@pytest.mark.skipif(
    not os.getenv("MODEL_SOURCE_ROOT"),
    reason="MODEL_SOURCE_ROOT is not configured; skipping external-vs-bundled comparison.",
)
def test_bundled_and_external_forward_predictions_match(monkeypatch: pytest.MonkeyPatch) -> None:
    external_settings = ForwardModelSettings.from_env()
    external_adapter = ForwardModelAdapter(external_settings)

    monkeypatch.delenv("MODEL_SOURCE_ROOT", raising=False)
    bundled_settings = ForwardModelSettings.from_env()
    bundled_adapter = ForwardModelAdapter(bundled_settings)

    request = parse_forward_csv(GOLDEN_INPUT)[0]
    external_response = external_adapter.predict(request)
    bundled_response = bundled_adapter.predict(request)

    assert bundled_settings.asset_source == "bundled"
    assert external_settings.asset_source == "external"
    for external_item, bundled_item in zip(external_response.predictions, bundled_response.predictions):
        assert external_item.position == bundled_item.position
        assert abs(external_item.concentration - bundled_item.concentration) <= 1e-6
