from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


APP_NAME = "Drug Gradient Chip"
LOG_DIR_NAME = "DrugGradientChip"
CREATE_NO_WINDOW = 0x08000000
STARTUP_TIMEOUT_SECONDS = 240
RUNTIME_RELOCATION_TIMEOUT_SECONDS = 600


def app_root() -> Path:
    executable = Path(sys.executable).resolve()
    if executable.parent.name.lower() == "runtime":
        candidate = executable.parent.parent
        if (candidate / "scripts" / "start_local_app.ps1").exists():
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


def run_start_script(root: Path, log_dir: Path, extra_args: list[str]) -> int:
    script = root / "scripts" / "start_local_app.ps1"
    stdout_log = log_dir / "launcher.stdout.log"
    stderr_log = log_dir / "launcher.stderr.log"
    command = [
        powershell_path(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-RuntimeMode",
        "Portable",
        "-HostAddress",
        "127.0.0.1",
        "-Port",
        "8000",
        "-StartupTimeoutSeconds",
        str(STARTUP_TIMEOUT_SECONDS),
        "-RuntimeRelocationTimeoutSeconds",
        str(RUNTIME_RELOCATION_TIMEOUT_SECONDS),
        *extra_args,
    ]
    append_log(stdout_log, "Launching: " + subprocess.list2cmdline(command))
    with stdout_log.open("a", encoding="utf-8") as stdout, stderr_log.open("a", encoding="utf-8") as stderr:
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=CREATE_NO_WINDOW,
                timeout=STARTUP_TIMEOUT_SECONDS + RUNTIME_RELOCATION_TIMEOUT_SECONDS + 60,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            append_log(stderr_log, "Startup command timed out. Attempting cleanup with stop_local_app.ps1.")
            cleanup_command = [
                powershell_path(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "scripts" / "stop_local_app.ps1"),
            ]
            subprocess.run(
                cleanup_command,
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=CREATE_NO_WINDOW,
                timeout=60,
                shell=False,
            )
            return 124
    return int(completed.returncode)


def main() -> int:
    root = app_root()
    log_dir = local_log_dir()
    marker = root / "runtime" / ".conda-unpacked"
    if not marker.exists():
        message_box(
            APP_NAME,
            "Drug Gradient Chip is preparing its local runtime for first use.\n"
            "This may take several minutes. The browser will open automatically when ready.",
            error=False,
        )
    extra_args = [arg for arg in sys.argv[1:] if arg]
    exit_code = run_start_script(root, log_dir, extra_args)
    if exit_code != 0:
        message_box(
            APP_NAME,
            "Application startup failed. You can try launching it again.\n\nSee logs at:\n" + str(log_dir),
            error=True,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
