from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read_wrapper(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_start_wrapper_preserves_powershell_exit_code_without_pause() -> None:
    script = _read_wrapper("start_app.cmd")

    assert "scripts\\start_local_app.ps1" in script
    assert "set \"EXIT_CODE=%ERRORLEVEL%\"" in script
    assert "exit /b %EXIT_CODE%" in script
    assert "pause" not in script.lower()


def test_lifecycle_wrappers_do_not_pause_automation_on_failure() -> None:
    for name in ("status_app.cmd", "stop_app.cmd"):
        script = _read_wrapper(name)

        assert "set \"EXIT_CODE=%ERRORLEVEL%\"" in script
        assert "exit /b %EXIT_CODE%" in script
        assert "pause" not in script.lower()


def test_start_script_launches_background_uvicorn_detached() -> None:
    script = (ROOT / "scripts" / "start_local_app.ps1").read_text(encoding="utf-8")

    assert "function StartUvicornDetached" in script
    assert "subprocess.DETACHED_PROCESS" in script
    assert "subprocess.CREATE_NEW_PROCESS_GROUP" in script
    assert "CREATE_BREAKAWAY_FROM_JOB" in script
    assert "Uvicorn launcher did not report a valid PID." in script
