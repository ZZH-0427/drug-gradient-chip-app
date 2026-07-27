from __future__ import annotations

import csv
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import ForwardModelSettings
from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.main import create_app
from app.model_runtime.input_parser import parse_forward_csv
from app.schemas.forward import ForwardPredictionItem, ForwardPredictionResponse

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "forward"
GOLDEN_INPUT = FIXTURE_DIR / "forward_prediction_input.csv"
GOLDEN_EXPECTED = FIXTURE_DIR / "forward_prediction_expected.csv"



def sample_payload() -> dict[str, object]:
    return {
        "sample_name": "DP 0",
        "inlet1": 1.0,
        "inlet2": 0.0,
        "chips": [
            {
                "position": position,
                "chip_type": chip_type,
                "left_width_mm": 0.1 + position,
                "right_width_mm": 0.2 + position,
                "left_bend_straight_distance_mm": 10.0 + position,
                "right_bend_straight_distance_mm": 20.0 + position,
            }
            for position, chip_type in enumerate(
                ["5to4", "4to2", "1to6", "2to4", "6to3", "3to1"],
                start=1,
            )
        ],
    }


class FakeForwardAdapter:
    def __init__(self) -> None:
        self.models = [SimpleNamespace(seed=44)]
        self.device = "cpu"
        self.predict_calls = 0

    def predict(self, request: object) -> ForwardPredictionResponse:
        self.predict_calls += 1
        return ForwardPredictionResponse(
            sample_name="DP 0",
            inlets={"inlet1": 1.0, "inlet2": 0.0},
            chip_count=6,
            predictions=[
                ForwardPredictionItem(
                    position=position,
                    point=f"y{position}",
                    chip_type=chip_type,
                    concentration=float(position),
                )
                for position, chip_type in enumerate(
                    ["5to4", "4to2", "1to6", "2to4", "6to3", "3to1"],
                    start=1,
                )
            ],
        )


class ErrorForwardAdapter(FakeForwardAdapter):
    def predict(self, request: object) -> ForwardPredictionResponse:
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_INFERENCE_FAILED,
            "Synthetic inference failure.",
        )


def test_health_returns_200_without_model() -> None:
    with TestClient(create_app(load_model=False)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "drug-gradient-chip-api"}


def test_model_status_ready_with_fake_adapter() -> None:
    with TestClient(create_app(adapter_factory=FakeForwardAdapter)) as client:
        response = client.get("/api/v1/model-status")

    assert response.status_code == 200
    assert response.json() == {
        "ready": True,
        "model_name": "physics-gnn",
        "supported_chip_counts": [6],
        "public_output": "concentration",
        "device": "cpu",
        "forward": {
            "ready": True,
            "supported_chip_counts": [6],
            "output": "concentration",
        },
        "reverse": {
            "ready": True,
            "supported_chip_counts": [6],
            "execution_mode": "async",
            "max_concurrent_tasks": 1,
        },
    }


def test_model_status_not_ready_returns_503() -> None:
    with TestClient(create_app(load_model=False)) as client:
        response = client.get("/api/v1/model-status")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_READY"


def test_forward_not_ready_returns_503() -> None:
    with TestClient(create_app(load_model=False)) as client:
        response = client.post("/api/v1/forward", json=sample_payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_READY"


def test_forward_with_fake_adapter_returns_six_predictions() -> None:
    with TestClient(create_app(adapter_factory=FakeForwardAdapter)) as client:
        response = client.post("/api/v1/forward", json=sample_payload())

    payload = response.json()
    assert response.status_code == 200
    assert len(payload["predictions"]) == 6
    first = payload["predictions"][0]
    assert first["position"] == 1
    assert first["concentration"] == 1.0
    assert "mean" not in first
    assert "std" not in first
    assert "seed_values" not in first


def test_forward_with_explicit_six_chip_count_returns_six_predictions() -> None:
    payload = sample_payload()
    payload["chip_count"] = 6

    with TestClient(create_app(adapter_factory=FakeForwardAdapter)) as client:
        response = client.post("/api/v1/forward", json=payload)

    assert response.status_code == 200
    assert len(response.json()["predictions"]) == 6


@pytest.mark.parametrize("chip_count", [4, 5, 7, 8])
def test_forward_rejects_supported_future_chip_counts_before_adapter_call(chip_count: int) -> None:
    adapter = FakeForwardAdapter()
    payload = sample_payload()
    payload["chip_count"] = chip_count
    payload["chips"] = payload["chips"][:chip_count]
    while len(payload["chips"]) < chip_count:
        position = len(payload["chips"]) + 1
        payload["chips"].append(
            {
                "position": position,
                "chip_type": "1to1",
                "left_width_mm": 0.1 + position,
                "right_width_mm": 0.2 + position,
                "left_bend_straight_distance_mm": 10.0 + position,
                "right_bend_straight_distance_mm": 20.0 + position,
            }
        )
    for index, chip in enumerate(payload["chips"], start=1):
        assert isinstance(chip, dict)
        chip["position"] = index

    with TestClient(create_app(adapter_factory=lambda: adapter)) as client:
        response = client.post("/api/v1/forward", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_CHIP_COUNT"
    assert "6" in body["error"]["message"]
    assert adapter.predict_calls == 0
    assert "pytorch_geometric-master" not in response.text
    assert "best_ablation_checkpoint.pt" not in response.text


@pytest.mark.parametrize("chip_count", [3, 9, 10])
def test_forward_rejects_out_of_range_chip_count_as_schema_error(chip_count: int) -> None:
    payload = sample_payload()
    payload["chip_count"] = chip_count

    with TestClient(create_app(adapter_factory=FakeForwardAdapter)) as client:
        response = client.post("/api/v1/forward", json=payload)

    assert response.status_code == 422
    assert "UNSUPPORTED_CHIP_COUNT" not in response.text


def test_forward_rejects_six_chip_count_with_five_rows_as_schema_error() -> None:
    payload = sample_payload()
    payload["chip_count"] = 6
    payload["chips"] = payload["chips"][:5]

    with TestClient(create_app(adapter_factory=FakeForwardAdapter)) as client:
        response = client.post("/api/v1/forward", json=payload)

    assert response.status_code == 422
    assert "UNSUPPORTED_CHIP_COUNT" not in response.text


def test_forward_rejects_chip_count_mismatch_as_schema_error() -> None:
    payload = sample_payload()
    payload["chip_count"] = 4

    with TestClient(create_app(adapter_factory=FakeForwardAdapter)) as client:
        response = client.post("/api/v1/forward", json=payload)

    assert response.status_code == 422
    assert "UNSUPPORTED_CHIP_COUNT" not in response.text


def test_forward_rejects_non_consecutive_positions_as_schema_error() -> None:
    payload = sample_payload()
    chips = payload["chips"]
    assert isinstance(chips, list)
    assert isinstance(chips[-1], dict)
    chips[-1]["position"] = 8

    with TestClient(create_app(adapter_factory=FakeForwardAdapter)) as client:
        response = client.post("/api/v1/forward", json=payload)

    assert response.status_code == 422


def test_forward_rejects_duplicate_positions_as_schema_error() -> None:
    payload = sample_payload()
    chips = payload["chips"]
    assert isinstance(chips, list)
    assert isinstance(chips[-1], dict)
    chips[-1]["position"] = 5

    with TestClient(create_app(adapter_factory=FakeForwardAdapter)) as client:
        response = client.post("/api/v1/forward", json=payload)

    assert response.status_code == 422


def test_invalid_forward_input_returns_422() -> None:
    payload = sample_payload()
    payload["chips"] = []

    with TestClient(create_app(adapter_factory=FakeForwardAdapter)) as client:
        response = client.post("/api/v1/forward", json=payload)

    assert response.status_code == 422


def test_adapter_created_once_and_reused_for_multiple_requests() -> None:
    calls: list[FakeForwardAdapter] = []

    def factory() -> FakeForwardAdapter:
        adapter = FakeForwardAdapter()
        calls.append(adapter)
        return adapter

    with TestClient(create_app(adapter_factory=factory)) as client:
        first = client.post("/api/v1/forward", json=sample_payload())
        second = client.post("/api/v1/forward", json=sample_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1
    assert calls[0].predict_calls == 2


def test_inference_error_returns_stable_500_without_traceback() -> None:
    with TestClient(create_app(adapter_factory=ErrorForwardAdapter)) as client:
        response = client.post("/api/v1/forward", json=sample_payload())

    payload = response.json()
    assert response.status_code == 500
    assert payload == {
        "error": {
            "code": "FORWARD_INFERENCE_ERROR",
            "message": "Synthetic inference failure.",
        }
    }
    assert "Traceback" not in response.text


def test_default_frontend_origin_allows_cors_preflight() -> None:
    with TestClient(create_app(load_model=False)) as client:
        response = client.options(
            "/api/v1/forward",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "Content-Type" in response.headers["access-control-allow-headers"]


def test_frontend_origins_are_trimmed_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "FRONTEND_ORIGINS",
        " http://example.test:5173, ,http://example.test:5173,http://other.test ",
    )

    with TestClient(create_app(load_model=False)) as client:
        allowed = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://example.test:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        disallowed = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://example.test:5173"
    assert disallowed.status_code == 400
    assert "access-control-allow-origin" not in disallowed.headers


def test_model_load_failure_keeps_app_alive_without_exposing_local_path() -> None:
    sensitive_path = (
        r"C:\private\model-assets\checkpoints"
        r"\seed_42\best_ablation_checkpoint.pt"
    )

    def factory() -> FakeForwardAdapter:
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_ASSET_NOT_FOUND,
            f"Missing model asset: {sensitive_path}",
        )

    with TestClient(create_app(adapter_factory=factory)) as client:
        health = client.get("/api/v1/health")
        status = client.get("/api/v1/model-status")
        forward = client.post("/api/v1/forward", json=sample_payload())

    expected_error = {
        "error": {
            "code": "MODEL_CONFIGURATION_ERROR",
            "message": "Forward model configuration is invalid.",
        }
    }

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "drug-gradient-chip-api",
    }

    assert status.status_code == 503
    assert status.json() == expected_error

    assert forward.status_code == 503
    assert forward.json() == expected_error

    for response in (status, forward):
        assert "pytorch_geometric-master" not in response.text
        assert "best_ablation_checkpoint.pt" not in response.text
        assert "Missing model asset" not in response.text


@pytest.mark.skipif(
    not GOLDEN_INPUT.exists(),
    reason="Golden fixture is not provisioned.",
)
def test_real_forward_api_matches_direct_adapter_golden_output() -> None:
    request = parse_forward_csv(GOLDEN_INPUT)[0]

    with TestClient(create_app()) as client:
        response = client.post("/api/v1/forward", json=request.model_dump())

    assert response.status_code == 200
    payload = response.json()

    with GOLDEN_EXPECTED.open(newline="", encoding="utf-8-sig") as handle:
        expected = next(csv.DictReader(handle))

    for item in payload["predictions"]:
        point = item["point"]
        chip = item["chip_type"]
        assert expected[f"{point}_chip_name"] == chip
        assert abs(item["concentration"] - float(expected[f"{point}_concentration"])) <= 1e-6
        assert "flow" not in item
        assert "mean" not in item
        assert "std" not in item
        assert "seed_values" not in item
