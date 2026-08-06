from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_launcher_uses_pythonw_safe_hidden_powershell() -> None:
    script = (ROOT / "launcher.pyw").read_text(encoding="utf-8")

    assert "Path(sys.executable).resolve()" in script
    assert 'executable.parent.name.lower() == "runtime"' in script
    assert "start_local_app.ps1" in script
    assert "RUNTIME_RELOCATION_TIMEOUT_SECONDS = 600" in script
    assert '"-RuntimeRelocationTimeoutSeconds",' in script
    assert "STARTUP_TIMEOUT_SECONDS + RUNTIME_RELOCATION_TIMEOUT_SECONDS + 60" in script
    assert "preparing its local runtime for first use" in script
    assert '"-RuntimeMode",' in script
    assert '"Portable",' in script
    assert '"-HostAddress",' in script
    assert '"127.0.0.1",' in script
    assert "creationflags=CREATE_NO_WINDOW" in script
    assert "shell=False" in script
    assert "stdout=stdout" in script
    assert "stderr=stderr" in script
    assert "LOCALAPPDATA" in script


def test_stopper_uses_safe_hidden_process_and_existing_lifecycle() -> None:
    script = (ROOT / "stopper.pyw").read_text(encoding="utf-8")

    assert "Path(sys.executable).resolve()" in script
    assert 'executable.parent.name.lower() == "runtime"' in script
    assert "stop_local_app.ps1" in script
    assert "creationflags=CREATE_NO_WINDOW" in script
    assert "shell=False" in script
    assert "stdout=stdout" in script
    assert "stderr=stderr" in script
    assert "taskkill" not in script.lower()


def test_inno_shortcuts_target_packaged_pythonw_launchers() -> None:
    script = (ROOT / "installer" / "windows" / "DrugGradientChip.iss").read_text(
        encoding="utf-8"
    )

    assert 'Filename: "{app}\\runtime\\pythonw.exe"' in script
    assert 'Parameters: """{app}\\launcher.pyw"""' in script
    assert 'Parameters: """{app}\\stopper.pyw"""' in script
    assert 'WorkingDir: "{app}"' in script
    assert 'IconFilename: "{app}\\resources\\drug-gradient-chip.ico"' in script
    assert "PrivilegesRequired=lowest" in script
    assert "initialize_installed_runtime.ps1" in script
    assert "RuntimeRelocationTimeoutSeconds 600" in script
    assert "Initializing local runtime. This may take several minutes" in script
    assert "[Run]" not in script
    assert "CurStepChanged" in script
    assert "CurStep = ssPostInstall" in script
    assert "ResultCode <> 0" in script
    assert "Abort;" in script
    assert "Local runtime initialization failed" in script


def test_installer_build_script_resolves_iscc_without_hardcoded_single_path() -> None:
    script = (ROOT / "scripts" / "build_windows_installer.ps1").read_text(
        encoding="utf-8"
    )

    assert "ISCC_PATH" in script
    assert "Get-Command ISCC.exe" in script
    assert "${env:ProgramFiles(x86)}\\Inno Setup 6\\ISCC.exe" in script
    assert "${env:ProgramFiles}\\Inno Setup 6\\ISCC.exe" in script
    assert "DGC_PACKAGE_ROOT" in script
    assert "DrugGradientChip-Setup-$Version-Windows-x64.exe" in script


def test_installer_package_includes_shared_runtime_initialization_scripts() -> None:
    script = (ROOT / "scripts" / "build_portable_package.ps1").read_text(
        encoding="utf-8"
    )

    assert '"portable_runtime.ps1"' in script
    assert '"initialize_installed_runtime.ps1"' in script


def test_start_script_uses_runtime_relocation_timeout_not_child_timeout() -> None:
    script = (ROOT / "scripts" / "start_local_app.ps1").read_text(encoding="utf-8")

    assert "[int]$RuntimeRelocationTimeoutSeconds = 600" in script
    assert "Ensure-PortableRuntimeReady -Root $root -LogsDir $logsDir -TimeoutSeconds $RuntimeRelocationTimeoutSeconds" in script
    assert "EnsurePortableRuntimeReady" not in script


def test_shared_runtime_initializer_uses_lock_marker_and_no_120s_timeout() -> None:
    script = (ROOT / "scripts" / "portable_runtime.ps1").read_text(encoding="utf-8")

    assert "Get-PortableRuntimeLockPath" in script
    assert "Invoke-PortableRuntimeWithLock" in script
    assert "TimeoutSeconds = 600" in script
    assert "Write-PortableRuntimeJsonAtomically -Path $marker" in script
    assert "Portable runtime is already relocated." in script
    assert "Process timed out after ${TimeoutSeconds}s" in script
    assert "120" not in script


def test_portable_build_requires_clean_git_unless_installer_allows_dirty() -> None:
    script = (ROOT / "scripts" / "build_portable_package.ps1").read_text(
        encoding="utf-8"
    )

    assert "[switch]$AllowDirty" in script
    assert "if (-not $AllowDirty) { Assert-CleanGit -Root $root }" in script
