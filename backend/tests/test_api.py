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
        self.models = [SimpleNamespace(seed=seed) for seed in [42, 52, 62, 72, 82]]
        self.ensemble = SimpleNamespace(device="cpu")
        self.predict_calls = 0

    def predict(self, request: object) -> ForwardPredictionResponse:
        self.predict_calls += 1
        return ForwardPredictionResponse(
            sample_name="DP 0",
            inlets={"inlet1": 1.0, "inlet2": 0.0},
            ensemble_seeds=[42, 52, 62, 72, 82],
            predictions=[
                ForwardPredictionItem(
                    position=position,
                    point=f"y{position}",
                    chip_type=chip_type,
                    mean=float(position),
                    std=float(position) / 10.0,
                    seed_values={
                        "42": float(position),
                        "52": float(position + 1),
                        "62": float(position + 2),
                        "72": float(position + 3),
                        "82": float(position + 4),
                    },
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
        "model_name": "forward-ensemble",
        "ensemble_size": 5,
        "seeds": [42, 52, 62, 72, 82],
        "device": "cpu",
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
    assert first["mean"] == 1.0
    assert first["std"] == 0.1
    assert first["seed_values"] == {
        "42": 1.0,
        "52": 2.0,
        "62": 3.0,
        "72": 4.0,
        "82": 5.0,
    }


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


def test_model_load_failure_keeps_app_alive_without_exposing_local_path() -> None:
    sensitive_path = (
        r"D:\pytorch_geometric-master\GNN\Physics-GNN\model"
        r"\ablation\data_only\seed_42\best_ablation_checkpoint.pt"
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

    # HTTP 服务本身仍然可用。
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "drug-gradient-chip-api",
    }

    # 模型状态接口返回稳定的通用错误。
    assert status.status_code == 503
    assert status.json() == expected_error

    # 正向预测接口在模型未就绪时返回同样的通用错误。
    assert forward.status_code == 503
    assert forward.json() == expected_error

    # 客户端响应不得暴露本地目录、checkpoint 名称或底层异常信息。
    for response in (status, forward):
        assert "pytorch_geometric-master" not in response.text
        assert "best_ablation_checkpoint.pt" not in response.text
        assert "Missing model asset" not in response.text


@pytest.mark.skipif(
    not os.getenv("MODEL_SOURCE_ROOT"),
    reason="MODEL_SOURCE_ROOT is not configured; skipping real API golden test.",
)
def test_real_forward_api_matches_direct_adapter_golden_output() -> None:
    settings = ForwardModelSettings.from_env()
    request = parse_forward_csv(settings.golden_input_path)[0]

    with TestClient(create_app()) as client:
        response = client.post("/api/v1/forward", json=request.model_dump())

    assert response.status_code == 200
    payload = response.json()

    with Path(settings.golden_output_path).open(newline="", encoding="utf-8-sig") as handle:
        expected = next(csv.DictReader(handle))

    for item in payload["predictions"]:
        point = item["point"]
        chip = item["chip_type"]
        assert expected[f"{point}_chip_name"] == chip
        assert abs(item["mean"] - float(expected[f"{point}_{chip}_pred_mean"])) <= 1e-6
        assert abs(item["std"] - float(expected[f"{point}_{chip}_pred_std"])) <= 1e-6
