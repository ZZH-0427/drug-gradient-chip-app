from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import DEFAULT_SEEDS, ForwardModelSettings
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
    assert manifest["ensemble_seeds"] == list(DEFAULT_SEEDS)
    assert [entry["relative_path"] for entry in manifest["files"]] == [
        "graph_template/physics_gnn_dataset.pt",
        "checkpoints/seed_42/best_ablation_checkpoint.pt",
        "checkpoints/seed_52/best_ablation_checkpoint.pt",
        "checkpoints/seed_62/best_ablation_checkpoint.pt",
        "checkpoints/seed_72/best_ablation_checkpoint.pt",
        "checkpoints/seed_82/best_ablation_checkpoint.pt",
    ]
    assert all("\\" not in entry["relative_path"] for entry in manifest["files"])
    assert all(entry["size_bytes"] > 0 for entry in manifest["files"])


def test_bundled_validate_assets_detects_missing_graph_template() -> None:
    asset_root = fresh_tmp_dir("missing_graph") / "forward"
    (asset_root / "graph_template").mkdir(parents=True, exist_ok=True)
    for seed in DEFAULT_SEEDS:
        checkpoint_dir = asset_root / "checkpoints" / f"seed_{seed}"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        (checkpoint_dir / "best_ablation_checkpoint.pt").write_bytes(b"x")

    settings = ForwardModelSettings(asset_root=asset_root, asset_source="bundled")

    try:
        settings.validate_assets()
    except Exception as exc:
        assert "missing or empty" in str(exc)
    else:
        raise AssertionError("validate_assets should fail when graph template is missing")


def test_bundled_validate_assets_detects_missing_checkpoint() -> None:
    asset_root = fresh_tmp_dir("missing_checkpoint") / "forward"
    (asset_root / "graph_template").mkdir(parents=True)
    (asset_root / "graph_template" / "physics_gnn_dataset.pt").write_bytes(b"x")
    (asset_root / "manifest.json").write_text("{}", encoding="utf-8")
    for seed in DEFAULT_SEEDS[:-1]:
        checkpoint_dir = asset_root / "checkpoints" / f"seed_{seed}"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        (checkpoint_dir / "best_ablation_checkpoint.pt").write_bytes(b"x")

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
