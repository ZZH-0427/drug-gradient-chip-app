from __future__ import annotations

import logging

import pytest

from app.core.config import ForwardModelSettings, resolve_forward_model_device
from app.core.errors import ModelRuntimeError


def test_forward_model_device_defaults_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORWARD_MODEL_DEVICE", raising=False)
    monkeypatch.delenv("MODEL_DEVICE", raising=False)

    assert resolve_forward_model_device() == "cpu"


def test_forward_model_device_falls_back_to_legacy_model_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FORWARD_MODEL_DEVICE", raising=False)
    monkeypatch.setenv("MODEL_DEVICE", "auto")

    assert resolve_forward_model_device() == "auto"


def test_forward_model_device_prefers_new_variable_and_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("FORWARD_MODEL_DEVICE", "cpu")
    monkeypatch.setenv("MODEL_DEVICE", "auto")

    with caplog.at_level(logging.WARNING):
        assert resolve_forward_model_device() == "cpu"

    assert "using FORWARD_MODEL_DEVICE" in caplog.text


def test_forward_model_device_rejects_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORWARD_MODEL_DEVICE", "gpu0")
    monkeypatch.delenv("MODEL_DEVICE", raising=False)

    with pytest.raises(ModelRuntimeError) as exc_info:
        resolve_forward_model_device()

    assert exc_info.value.code == "MODEL_CONFIGURATION_ERROR"


def test_settings_from_env_uses_new_device_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_SOURCE_ROOT", "C:\\model-root")
    monkeypatch.setenv("FORWARD_MODEL_DEVICE", "cpu")
    monkeypatch.setenv("MODEL_DEVICE", "auto")

    settings = ForwardModelSettings.from_env()

    assert str(settings.model_source_root) == "C:\\model-root"
    assert settings.device == "cpu"
