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


def test_lifecycle_identity_accepts_runtime_identity_when_command_line_is_unreadable(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "app-process-identity.json"
    script = f"""
. "{COMMON_SCRIPT}"
$root = "D:\\App"
$identityFile = "{identity_file}"
@{{
  schema_version = 1
  pid = 1234
  identity_token = "token-1"
  application_root = $root
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = "8000"
}} | ConvertTo-Json | Set-Content -LiteralPath $identityFile -Encoding UTF8
$state = [pscustomobject]@{{
  pid = 1234
  process_start_time_utc = "2026-07-27T04:00:00.0000000Z"
  executable_path = "D:\\Tools\\python.exe"
  application_root = $root
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = 8000
  identity_file = $identityFile
  identity_token = "token-1"
}}
$proc = [pscustomobject]@{{
  ProcessId = 1234
  CreationTimeUtc = "2026-07-27T04:00:00.5000000Z"
  ExecutablePath = "D:\\Tools\\python.exe"
  CommandLine = ""
}}
Test-LocalAppProcessIdentity -State $state -Root $root -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "True"


def test_lifecycle_identity_reads_utf8_no_bom_chinese_identity_file(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "app-process-identity.json"
    identity_file.write_text(
        """
{
  "schema_version": 1,
  "pid": 1234,
  "identity_token": "token-1",
  "application_root": "D:\\\\安装版 Drug Gradient Chip rc7 中文",
  "app_module": "backend.app.main:app",
  "host": "127.0.0.1",
  "port": "8000"
}
""".strip(),
        encoding="utf-8",
    )
    script = f"""
. "{COMMON_SCRIPT}"
$identityFile = "{identity_file}"
$root = [string]((Get-Content -LiteralPath $identityFile -Raw -Encoding UTF8 | ConvertFrom-Json).application_root)
$state = [pscustomobject]@{{
  pid = 1234
  process_start_time_utc = "2026-07-27T04:00:00.0000000Z"
  executable_path = "D:\\Tools\\python.exe"
  application_root = $root
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = 8000
  identity_file = $identityFile
  identity_token = "token-1"
}}
$proc = [pscustomobject]@{{
  ProcessId = 1234
  CreationTimeUtc = "2026-07-27T04:00:00.5000000Z"
  ExecutablePath = "D:\\Tools\\python.exe"
  CommandLine = ""
}}
Test-LocalAppProcessIdentity -State $state -Root $root -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "True"


def test_lifecycle_identity_prefers_matching_runtime_identity_over_command_line(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "app-process-identity.json"
    script = f"""
. "{COMMON_SCRIPT}"
$root = "D:\\App"
@{{
  schema_version = 1
  pid = 1234
  identity_token = "token-1"
  application_root = $root
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = "8000"
}} | ConvertTo-Json | Set-Content -LiteralPath "{identity_file}" -Encoding UTF8
$state = [pscustomobject]@{{
  pid = 1234
  process_start_time_utc = "2026-07-27T04:00:00.0000000Z"
  executable_path = "D:\\Tools\\python.exe"
  application_root = $root
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = 8000
  identity_file = "{identity_file}"
  identity_token = "token-1"
}}
$proc = [pscustomobject]@{{
  ProcessId = 1234
  CreationTimeUtc = "2026-07-27T04:00:00.5000000Z"
  ExecutablePath = "D:\\Tools\\python.exe"
  CommandLine = '"D:\\Tools\\python.exe" -m uvicorn backend.app.main:app --app-dir D:\\MojibakePath --host 127.0.0.1 --port 8000'
}}
Test-LocalAppProcessIdentity -State $state -Root $root -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "True"


def test_lifecycle_identity_rejects_empty_command_line_without_runtime_identity(
    tmp_path: Path,
) -> None:
    script = f"""
. "{COMMON_SCRIPT}"
$root = "D:\\App"
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
  ExecutablePath = "D:\\Tools\\python.exe"
  CommandLine = ""
}}
Test-LocalAppProcessIdentity -State $state -Root $root -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "False"


def test_lifecycle_identity_rejects_runtime_identity_token_mismatch(tmp_path: Path) -> None:
    identity_file = tmp_path / "app-process-identity.json"
    script = f"""
. "{COMMON_SCRIPT}"
$root = "D:\\App"
@{{
  schema_version = 1
  pid = 1234
  identity_token = "other-token"
  application_root = $root
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = "8000"
}} | ConvertTo-Json | Set-Content -LiteralPath "{identity_file}" -Encoding UTF8
$state = [pscustomobject]@{{
  pid = 1234
  process_start_time_utc = "2026-07-27T04:00:00.0000000Z"
  executable_path = "D:\\Tools\\python.exe"
  application_root = $root
  app_module = "backend.app.main:app"
  host = "127.0.0.1"
  port = 8000
  identity_file = "{identity_file}"
  identity_token = "token-1"
}}
$proc = [pscustomobject]@{{
  ProcessId = 1234
  CreationTimeUtc = "2026-07-27T04:00:00.5000000Z"
  ExecutablePath = "D:\\Tools\\python.exe"
  CommandLine = ""
}}
Test-LocalAppProcessIdentity -State $state -Root $root -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "False"


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


def test_lifecycle_identity_rejects_different_app_module(tmp_path: Path) -> None:
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
  CommandLine = '"D:\\Tools\\python.exe" -m uvicorn other.app:app --app-dir D:\\App --host 127.0.0.1 --port 8000'
}}
Test-LocalAppProcessIdentity -State $state -Root "D:\\App" -ProcessInfo $proc
"""

    assert run_powershell(script, tmp_path) == "False"
