from __future__ import annotations

import sys

from desktop_shell import app_root, browser_mode, desktop_mode, local_log_dir


def main() -> int:
    root = app_root()
    log_dir = local_log_dir()
    args = [arg for arg in sys.argv[1:] if arg]
    lower = {arg.lower() for arg in args}
    browser = "--browser-mode" in lower or "-browsermode" in lower
    forwarded = [arg for arg in args if arg.lower() not in {"--browser-mode", "-browsermode"}]
    if browser:
        return browser_mode(root, log_dir, forwarded)
    return desktop_mode(root, log_dir, forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
