from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_pywebview_dependencies_are_pinned_without_ml_version_changes() -> None:
    lock = (ROOT / "requirements-py311-lock.txt").read_text(encoding="utf-8")
    environment = (ROOT / "environment-py311.yml").read_text(encoding="utf-8")
    portable_environment = (ROOT / "environment-portable-cpu.yml").read_text(
        encoding="utf-8"
    )
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    for expected in (
        "pywebview==6.2.1",
        "pythonnet==3.1.0",
        "proxy_tools==0.1.0",
        "bottle==0.13.4",
        "clr_loader==0.3.1",
        "cffi==2.1.1",
        "pycparser==3.0",
    ):
        assert expected in lock

    for expected in (
        "pywebview==6.2.1",
        "pythonnet==3.1.0",
        "proxy-tools==0.1.0",
        "bottle==0.13.4",
        "clr-loader==0.3.1",
        "cffi==2.1.1",
        "pycparser==3.0",
    ):
        assert expected in environment
        assert expected in portable_environment

    assert '"pywebview==6.2.1"' in pyproject
    assert "torch==2.9.0+cu128" in lock
    assert "torch-geometric==2.8.0" in lock
    assert "numpy==2.4.6" in lock
    assert "scipy==1.17.1" in lock
