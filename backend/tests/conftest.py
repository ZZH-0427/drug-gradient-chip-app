from __future__ import annotations

import os
from pathlib import Path
from typing import Any


if os.name == "nt":
    _original_path_mkdir = Path.mkdir

    def _mkdir_without_private_windows_acl(
        self: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        # Python 3.11 on Windows applies 0o700 by creating a private ACL.
        # In this environment that ACL can make pytest's tmp_path basetemp
        # unreadable by the same user during session teardown.  Keep the
        # patch test-only and only relax the problematic private mode.
        if mode == 0o700:
            mode = 0o777
        return _original_path_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)

    Path.mkdir = _mkdir_without_private_windows_acl  # type: ignore[method-assign]


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    if os.name != "nt":
        return
    Path.mkdir = _original_path_mkdir  # type: ignore[method-assign]
