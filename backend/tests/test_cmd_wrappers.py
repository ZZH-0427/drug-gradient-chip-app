from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read_wrapper(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_start_wrapper_preserves_powershell_exit_code_without_pause() -> None:
    script = _read_wrapper("start_app.cmd")

    assert "scripts\\start_local_app.ps1" in script
    assert "runtime\\pythonw.exe" in script
    assert "launcher.pyw" in script
    assert 'if /I "%~1"=="-NoBrowser" goto lifecycle' in script
    assert "set \"EXIT_CODE=%ERRORLEVEL%\"" in script
    assert "exit /b %EXIT_CODE%" in script
    assert "pause" not in script.lower()


def test_lifecycle_wrappers_do_not_pause_automation_on_failure() -> None:
    for name in ("browser_app.cmd", "status_app.cmd", "stop_app.cmd"):
        script = _read_wrapper(name)

        assert "set \"EXIT_CODE=%ERRORLEVEL%\"" in script
        assert "exit /b %EXIT_CODE%" in script
        assert "pause" not in script.lower()


def test_browser_mode_wrapper_routes_through_launcher_flag() -> None:
    script = _read_wrapper("browser_app.cmd")

    assert "launcher.pyw\" --browser-mode" in script
    assert "scripts\\start_local_app.ps1" in script


def test_start_script_launches_background_uvicorn_detached() -> None:
    script = (ROOT / "scripts" / "start_local_app.ps1").read_text(encoding="utf-8")

    assert "function StartUvicornDetached" in script
    assert "subprocess.DETACHED_PROCESS" in script
    assert "subprocess.CREATE_NEW_PROCESS_GROUP" in script
    assert "CREATE_BREAKAWAY_FROM_JOB" in script
    assert "Uvicorn launcher did not report a valid PID." in script


def test_start_script_omits_empty_argument_list_for_no_arg_processes() -> None:
    script = (ROOT / "scripts" / "start_local_app.ps1").read_text(encoding="utf-8")

    assert 'if ($null -ne $ArgumentList -and $ArgumentList.Count -gt 0)' in script
    assert '$startParams["ArgumentList"] = @($ArgumentList | ForEach-Object { Quote-ProcessArgument -Value $_ })' in script


def test_asset_verification_arguments_are_not_prequoted_twice() -> None:
    script = (ROOT / "scripts" / "start_local_app.ps1").read_text(encoding="utf-8")

    assert '$verify = InvokeProcessWithTimeout -FilePath "powershell.exe" -ArgumentList $verifyArgs' in script
    assert "$verifyProcessArgs" not in script


def test_start_script_writes_runtime_identity_from_powershell() -> None:
    script = (ROOT / "scripts" / "start_local_app.ps1").read_text(encoding="utf-8")

    assert "Write-PortableRuntimeJsonAtomically -Path $identityFile" in script
    assert "application_root = $root" in script
    assert "identity_token = $identityToken" in script


def test_stop_script_cleans_reverse_workers_even_for_stale_app_state() -> None:
    script = (ROOT / "scripts" / "stop_local_app.ps1").read_text(encoding="utf-8")

    assert "Stop-ReverseWorkers -Root $root" in script
    assert "Stale PID found; state file removed." in script
    assert "runtime\\python.exe" in script
    assert "reverse_tasks" in script
    assert "Stopping reverse worker PID $workerPid from task state." in script
