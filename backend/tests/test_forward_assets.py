from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import ForwardModelSettings
from app.main import create_app


TMP_ROOT = Path(__file__).resolve().parent / "_tmp_assets"


def fresh_tmp_dir(name: str) -> Path:
    path = TMP_ROOT / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_bundled_manifest_has_expected_runtime_assets(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_SOURCE_ROOT", raising=False)
    settings = ForwardModelSettings.from_env()
    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))

    assert settings.asset_source == "bundled"
    assert manifest["schema_version"] == 1
    assert manifest["model_family"] == "PhysicsGuidedDualTaskGNN"
    assert manifest["checkpoint_file"] == "best_concentration_checkpoint.pt"
    assert manifest["checkpoint_sha256"] == "f6f80287d3b04145daf01c5267f7b304cca88bd2331d380063f49d43b6ead0cc"
    assert manifest["checkpoint_size_bytes"] > 0
    assert manifest["supported_forward_chip_counts"] == [6]
    assert manifest["supported_reverse_chip_counts"] == [6]
    assert manifest["public_forward_output"] == "concentration_only"
    assert "\\" not in manifest["checkpoint_file"]


def test_bundled_validate_assets_detects_missing_checkpoint() -> None:
    asset_root = fresh_tmp_dir("missing_checkpoint") / "physics_gnn"
    asset_root.mkdir(parents=True)
    (asset_root / "manifest.json").write_text("{}", encoding="utf-8")

    settings = ForwardModelSettings(asset_root=asset_root, asset_source="bundled")

    try:
        settings.validate_assets()
    except Exception as exc:
        assert "missing or empty" in str(exc)
    else:
        raise AssertionError("validate_assets should fail when a checkpoint is missing")


def test_missing_bundled_assets_return_503_without_absolute_path() -> None:
    missing_root = fresh_tmp_dir("missing_for_api") / "missing"

    def factory() -> object:
        settings = ForwardModelSettings(asset_root=missing_root, asset_source="bundled")
        settings.validate_assets()
        raise AssertionError("unreachable")

    with TestClient(create_app(adapter_factory=factory)) as client:
        status = client.get("/api/v1/model-status")

    assert status.status_code == 503
    payload = status.json()
    assert payload["error"]["code"] == "MODEL_CONFIGURATION_ERROR"
    assert str(missing_root) not in status.text
