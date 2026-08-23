from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_launcher_defaults_to_desktop_shell_and_keeps_browser_mode() -> None:
    script = (ROOT / "launcher.pyw").read_text(encoding="utf-8")

    assert "desktop_mode(root, log_dir, forwarded)" in script
    assert "browser_mode(root, log_dir, forwarded)" in script
    assert "--browser-mode" in script


def test_desktop_shell_uses_pywebview_edge_runtime_and_safe_backend_lifecycle() -> None:
    script = (ROOT / "desktop_shell.py").read_text(encoding="utf-8")

    assert "import webview" in script
    assert 'gui="edgechromium"' in script
    assert "webview2_runtime_version" in script
    assert "Microsoft Edge WebView2 Runtime was not found" in script
    assert "send_activation()" in script
    assert "DesktopIpcServer" in script
    assert "IPC_PORT = 48731" in script
    assert "active_reverse_task_exists" in script
    assert "A reverse prediction task is still running" in script
    assert "run_stop_script(self.root, self.log_dir)" in script
    assert "ALLOWED_ORIGIN" in script
    assert "webbrowser.open(current)" in script
    assert "js_api" not in script


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
    assert "Drug Gradient Chip - Browser Mode" in script
    assert "MicrosoftEdgeWebView2RuntimeInstallerX64.exe" in script
    assert "EnsureWebView2Runtime" in script
    assert "WebView2 Runtime already installed" in script
    assert "WebView2 Runtime installation failed" in script
    assert "StopExistingApplication" in script
    assert "CurStep = ssInstall" in script
    assert 'stopper.pyw' in script


def test_installer_build_script_resolves_iscc_without_hardcoded_single_path() -> None:
    script = (ROOT / "scripts" / "build_windows_installer.ps1").read_text(
        encoding="utf-8"
    )

    assert "ISCC_PATH" in script
    assert "WEBVIEW2_INSTALLER_PATH" in script
    assert "Resolve-WebView2Installer" in script
    assert "WebView2 installer is too small" in script
    assert "Get-AuthenticodeSignature" in script
    assert "Microsoft Corporation" in script
    assert "webview2_installer_sha256" in script
    assert "webview2_installer_size" in script
    assert "webview2_installer_file_version" in script
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
    assert '"browser_app.cmd"' in script
    assert '"desktop_shell.py"' in script
    assert "default_launch_mode = \"desktop-shell\"" in script
    assert "desktop_shell_renderer = \"edgechromium\"" in script
    assert "pywebview_version = $coreVersions.pywebview" in script
    assert "Remove-WindowsPythonScriptShebangDevPaths" in script
    assert "#!python.exe" in script


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
    assert 'Scripts\\conda-unpack-script.py' in script
    assert '"python.exe"' in script
    assert "Invoke-PortableRuntimeProcessWithTimeout -FilePath $runtimePython" in script
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


def test_portable_build_uses_development_python_for_pytest_only() -> None:
    script = (ROOT / "scripts" / "build_portable_package.ps1").read_text(
        encoding="utf-8"
    )

    assert "$appPython = Get-CondaPython -Name $runtimeEnvironment" in script
    assert "$testPython = Get-CondaPython -Name $CondaEnvironment" in script
    assert 'Run-Checked -FilePath $appPython -Arguments @("-m", "pip", "check")' in script
    assert 'Run-Checked -FilePath $testPython -Arguments @("-m", "pytest", "-q", "--basetemp=.pytest_tmp")' in script
    assert "Get-CoreVersions -Python $appPython" in script
    assert 'CPU portable package requires a CPU-only torch build' in script
    assert 'Run-Checked -FilePath $appPython -Arguments @("-m", "pytest"' not in script


def test_installer_build_preserves_source_baseline_and_builder_commits() -> None:
    script = (ROOT / "scripts" / "build_windows_installer.ps1").read_text(
        encoding="utf-8"
    )

    assert '[string]$SourceCommit = ""' in script
    assert '[string]$ProductFeatureBaseline = ""' in script
    assert '$commit = Get-CommandOutput -FilePath "git" -Arguments @("rev-parse", "HEAD")' in script
    assert "$sourceCommitForPackage = if ($SourceCommit.Trim())" in script
    assert "$featureBaselineForPackage = if ($ProductFeatureBaseline.Trim())" in script
    assert '"-SourceCommit", $sourceCommitForPackage' in script
    assert '"-ProductFeatureBaseline", $featureBaselineForPackage' in script
    assert "source_commit -NotePropertyValue $sourceCommitForPackage" in script
    assert "product_feature_baseline -NotePropertyValue $featureBaselineForPackage" in script
    assert "builder_commit -NotePropertyValue $commit" in script
    assert "Source commit: $sourceCommitForPackage" in script
    assert "Product feature baseline: $featureBaselineForPackage" in script
    assert "Builder commit: $commit" in script
    assert "product_feature_baseline -NotePropertyValue $commit" not in script
