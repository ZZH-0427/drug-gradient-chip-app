from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON_SCRIPT = ROOT / "scripts" / "local_app_lifecycle.ps1"
START_SCRIPT = ROOT / "scripts" / "start_local_app.ps1"


def run_powershell(script: str, tmp_path: Path) -> str:
    script_path = tmp_path / "check.ps1"
    script_path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def test_start_script_passes_app_dir_to_uvicorn() -> None:
    content = START_SCRIPT.read_text(encoding="utf-8")

    assert '"--app-dir", $root' in content
    assert '"backend.app.main:app", "--app-dir", $root' in content


def test_lifecycle_identity_accepts_matching_process_metadata(tmp_path: Path) -> None:
    script = f"""
. "{COMMON_SCRIPT}"
$root = "D:\\Temp Path\\药物芯片"
$state = [pscustomobject]@{{
  pid = 1234
  process_start_time_utc = "2026-07-27T04:00:00.0000000Z"
  executable_path = "D:\\Tools\\python.exe"
  application_root = $root
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = 8000
}}
$proc = [pscustomobject]@{{
  ProcessId = 1234
  CreationTimeUtc = "2026-07-27T04:00:00.5000000Z"
  ExecutablePath = "D:/Tools/python.exe"
  CommandLine = '"D:\\Tools\\python.exe" -m uvicorn backend.app.main:app --app-dir "D:\\Temp Path\\药物芯片\\" --host 127.0.0.1 --port 8000'
}}
Test-LocalAppProcessIdentity -State $state -Root "D:/Temp Path/药物芯片/" -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "True"


def test_lifecycle_identity_rejects_pid_reuse_by_start_time(tmp_path: Path) -> None:
    script = f"""
. "{COMMON_SCRIPT}"
$state = [pscustomobject]@{{
  pid = 1234
  process_start_time_utc = "2026-07-27T04:00:00.0000000Z"
  executable_path = "D:\\Tools\\python.exe"
  application_root = "D:\\App"
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = 8000
}}
$proc = [pscustomobject]@{{
  ProcessId = 1234
  CreationTimeUtc = "2026-07-27T04:05:00.0000000Z"
  ExecutablePath = "D:\\Tools\\python.exe"
  CommandLine = '"D:\\Tools\\python.exe" -m uvicorn backend.app.main:app --app-dir D:\\App --host 127.0.0.1 --port 8000'
}}
Test-LocalAppProcessIdentity -State $state -Root "D:\\App" -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "False"


def test_lifecycle_identity_rejects_tampered_application_root(tmp_path: Path) -> None:
    script = f"""
. "{COMMON_SCRIPT}"
$state = [pscustomobject]@{{
  pid = 1234
  process_start_time_utc = "2026-07-27T04:00:00.0000000Z"
  executable_path = "D:\\Tools\\python.exe"
  application_root = "D:\\OtherApp"
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = 8000
}}
$proc = [pscustomobject]@{{
  ProcessId = 1234
  CreationTimeUtc = "2026-07-27T04:00:00.0000000Z"
  ExecutablePath = "D:\\Tools\\python.exe"
  CommandLine = '"D:\\Tools\\python.exe" -m uvicorn backend.app.main:app --app-dir D:\\OtherApp --host 127.0.0.1 --port 8000'
}}
Test-LocalAppProcessIdentity -State $state -Root "D:\\App" -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "False"


def test_lifecycle_identity_rejects_different_app_dir(tmp_path: Path) -> None:
    script = f"""
. "{COMMON_SCRIPT}"
$state = [pscustomobject]@{{
  pid = 1234
  process_start_time_utc = "2026-07-27T04:00:00.0000000Z"
  executable_path = "D:\\Tools\\python.exe"
  application_root = "D:\\App"
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = 8000
}}
$proc = [pscustomobject]@{{
  ProcessId = 1234
  CreationTimeUtc = "2026-07-27T04:00:00.0000000Z"
  ExecutablePath = "D:\\Tools\\python.exe"
  CommandLine = '"D:\\Tools\\python.exe" -m uvicorn backend.app.main:app --app-dir D:\\DifferentApp --host 127.0.0.1 --port 8000'
}}
Test-LocalAppProcessIdentity -State $state -Root "D:\\App" -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "False"
