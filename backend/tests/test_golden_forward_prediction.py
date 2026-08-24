from __future__ import annotations

import csv
import importlib.util
import os
import sys
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
SOURCE_FIXED_FORWARD = (
    Path("D:/pytorch_geometric-master")
    / "正向预测与反向预测"
    / "正向预测"
    / "forward_predict.py"
)


def _float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def _load_source_fixed_forward_module():
    if not SOURCE_FIXED_FORWARD.exists():
        pytest.skip(f"Source fixed-six forward script not found: {SOURCE_FIXED_FORWARD}")
    spec = importlib.util.spec_from_file_location("source_fixed_forward_predict", SOURCE_FIXED_FORWARD)
    if spec is None or spec.loader is None:
        pytest.skip(f"Unable to import source fixed-six forward script: {SOURCE_FIXED_FORWARD}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _source_sample_from_request(module, request):
    return module.InputSample(
        sample_name=request.sample_name,
        inlet1=float(request.inlet1),
        inlet2=float(request.inlet2),
        chips=tuple(
            module.InputChip(
                chip_name=chip.chip_type,
                left_width_mm=float(chip.left_width_mm),
                right_width_mm=float(chip.right_width_mm),
                left_distance_mm=float(chip.left_bend_straight_distance_mm),
                right_distance_mm=float(chip.right_bend_straight_distance_mm),
                left_position=float(chip.position),
                right_position=float(chip.position),
            )
            for chip in request.chips_by_position()
        ),
    )


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


def test_fixed_six_forward_matches_source_forward_predict_script() -> None:
    source_forward = _load_source_fixed_forward_module()
    settings = ForwardModelSettings.from_env()
    adapter = ForwardModelAdapter(settings)
    request = parse_forward_csv(GOLDEN_INPUT)[0]

    source_model = source_forward.load_dualtask_model(adapter.model_info.checkpoint_path, adapter.device)
    expected, _, _ = source_forward.predict([_source_sample_from_request(source_forward, request)], source_model, adapter.device)
    actual = adapter.predict(request)

    assert expected.shape == (1, 6)
    assert actual.chip_count == 6
    assert [item.point for item in actual.predictions] == [f"y{index}" for index in range(1, 7)]
    absolute_differences = [
        abs(prediction.concentration - float(expected[0, index]))
        for index, prediction in enumerate(actual.predictions)
    ]
    assert max(absolute_differences) <= 1e-6


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
