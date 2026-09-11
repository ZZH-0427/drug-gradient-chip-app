from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


APP_NAME = "智能药物浓度预测平台"
LOG_DIR_NAME = "DrugGradientChip"
CREATE_NO_WINDOW = 0x08000000


def app_root() -> Path:
    executable = Path(sys.executable).resolve()
    if executable.parent.name.lower() == "runtime":
        candidate = executable.parent.parent
        if (candidate / "scripts" / "stop_local_app.ps1").exists():
            return candidate
    return Path(__file__).resolve().parent


def local_log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else (Path.home() / "AppData" / "Local")
    path = root / LOG_DIR_NAME / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def powershell_path() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate if candidate.exists() else "powershell.exe")


def message_box(title: str, message: str, error: bool = False) -> None:
    flags = 0x10 if error else 0x40
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, flags)
    except Exception:
        pass


def append_log(path: Path, text: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{stamp}] {text}\n")


def main() -> int:
    root = app_root()
    quiet = any(arg.lower() == "--quiet" for arg in sys.argv[1:])
    log_dir = local_log_dir()
    stdout_log = log_dir / "stopper.stdout.log"
    stderr_log = log_dir / "stopper.stderr.log"
    command = [
        powershell_path(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(root / "scripts" / "stop_local_app.ps1"),
    ]
    append_log(stdout_log, "Stopping: " + subprocess.list2cmdline(command))
    with stdout_log.open("a", encoding="utf-8") as stdout, stderr_log.open("a", encoding="utf-8") as stderr:
        completed = subprocess.run(
            command,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=CREATE_NO_WINDOW,
            timeout=90,
            shell=False,
        )
    if completed.returncode != 0:
        message_box(
            APP_NAME,
            "Application stop failed. See logs at:\n" + str(log_dir),
            error=True,
        )
    elif not quiet:
        message_box(APP_NAME, "Application stopped.", error=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
