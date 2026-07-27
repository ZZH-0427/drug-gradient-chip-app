from __future__ import annotations

import logging
from pathlib import Path

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
    assert settings.asset_source == "external"


def test_settings_uses_bundled_assets_when_model_source_root_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MODEL_SOURCE_ROOT", raising=False)
    monkeypatch.setenv("FORWARD_MODEL_DEVICE", "cpu")

    settings = ForwardModelSettings.from_env()

    assert settings.asset_source == "bundled"
    assert settings.model_source_root is None
    assert settings.asset_root.name == "physics_gnn"
    assert settings.manifest_path.name == "manifest.json"
    assert settings.seeds == (44,)
    assert settings.checkpoint_path(44).name == "best_concentration_checkpoint.pt"


def test_settings_uses_bundled_assets_when_model_source_root_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_SOURCE_ROOT", "   ")

    settings = ForwardModelSettings.from_env()

    assert settings.asset_source == "bundled"


def test_settings_uses_external_assets_when_model_source_root_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_SOURCE_ROOT", "C:\\model-root")

    settings = ForwardModelSettings.from_env()

    assert settings.asset_source == "external"
    assert (
        str(settings.checkpoint_path(44))
        == "C:\\model-root\\GNN\\Physics-GNN\\model\\experiment_D_balanced_medium_weight\\seed_44\\best_concentration_checkpoint.pt"
    )


def test_invalid_external_path_does_not_fallback_to_bundled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_SOURCE_ROOT", "Z:\\missing-model-root")
    settings = ForwardModelSettings.from_env()

    with pytest.raises(ModelRuntimeError) as exc_info:
        settings.validate_assets()

    assert settings.asset_source == "external"
    assert exc_info.value.code == "MODEL_CONFIGURATION_ERROR"


def test_bundled_asset_paths_do_not_depend_on_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MODEL_SOURCE_ROOT", raising=False)
    monkeypatch.chdir(Path(__file__).resolve().parent)

    settings = ForwardModelSettings.from_env()

    assert settings.asset_source == "bundled"
    assert "drug-gradient-chip-app" in str(settings.asset_root)
    assert settings.asset_root.is_absolute()
