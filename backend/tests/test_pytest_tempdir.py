from __future__ import annotations

from pathlib import Path


def test_tmp_path_remains_listable_on_windows(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    marker.write_text("ok", encoding="utf-8")

    assert marker in list(tmp_path.iterdir())
