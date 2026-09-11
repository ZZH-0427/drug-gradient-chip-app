from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


APP_NAME = "智能药物浓度预测平台"
LOG_DIR_NAME = "DrugGradientChip"
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
IPC_PORT = 48731
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 820
MIN_WIDTH = 1000
MIN_HEIGHT = 680
CREATE_NO_WINDOW = 0x08000000
STARTUP_TIMEOUT_SECONDS = 240
RUNTIME_RELOCATION_TIMEOUT_SECONDS = 600
ALLOWED_ORIGIN = f"http://{LOCAL_HOST}:{DEFAULT_PORT}"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def app_root() -> Path:
    executable = Path(sys.executable).resolve()
    if executable.parent.name.lower() == "runtime":
        package_root = executable.parent.parent
        if (package_root / "scripts" / "start_local_app.ps1").exists():
            return package_root
    return Path(__file__).resolve().parent


def local_log_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    path = base / LOG_DIR_NAME / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def powershell_path() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.exists() else "powershell.exe"


def append_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{utc_stamp()}] {text}\n")


def log_exception(path: Path, context: str) -> None:
    append_log(path, context)
    with path.open("a", encoding="utf-8") as handle:
        traceback.print_exc(file=handle)


def message_box(title: str, message: str, *, error: bool = False, yes_no: bool = False) -> int:
    flags = 0x10 if error else 0x40
    if yes_no:
        flags |= 0x04
    return ctypes.windll.user32.MessageBoxW(None, message, title, flags)


def webview2_runtime_version() -> str:
    try:
        import winreg
    except ImportError:
        return ""

    key_paths = (
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
    )
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    for root in roots:
        for key_path in key_paths:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, "pv")
                    if str(value).strip():
                        return str(value).strip()
            except OSError:
                continue
    return ""


def active_reverse_task_exists(root: Path) -> bool:
    tasks_root = root / ".runtime" / "reverse_tasks"
    if not tasks_root.exists():
        return False
    for state_file in tasks_root.glob("*/state.json"):
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("status") in {"queued", "running"}:
            return True
    return False


def run_start_script(root: Path, log_dir: Path, *, browser: bool, extra_args: list[str]) -> int:
    stdout_log = log_dir / "launcher.stdout.log"
    stderr_log = log_dir / "launcher.stderr.log"
    script = root / "scripts" / "start_local_app.ps1"
    args = [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-HostAddress",
        LOCAL_HOST,
        "-Port",
        str(DEFAULT_PORT),
        "-StartupTimeoutSeconds",
        str(STARTUP_TIMEOUT_SECONDS),
        "-RuntimeRelocationTimeoutSeconds",
        str(RUNTIME_RELOCATION_TIMEOUT_SECONDS),
    ]
    if (root / "runtime" / "python.exe").exists():
        args.extend(["-RuntimeMode", "Portable"])
    if not browser:
        args.append("-NoBrowser")
    args.extend(extra_args)
    append_log(stdout_log, "Starting local backend through start_local_app.ps1.")
    with stdout_log.open("ab") as stdout, stderr_log.open("ab") as stderr:
        completed = subprocess.run(
            [powershell_path(), *args],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    return completed.returncode


def run_stop_script(root: Path, log_dir: Path) -> int:
    stdout_log = log_dir / "launcher.stdout.log"
    stderr_log = log_dir / "launcher.stderr.log"
    script = root / "scripts" / "stop_local_app.ps1"
    args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    with stdout_log.open("ab") as stdout, stderr_log.open("ab") as stderr:
        completed = subprocess.run(
            [powershell_path(), *args],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    return completed.returncode


def send_activation(host: str = LOCAL_HOST, port: int = IPC_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5) as client:
            client.sendall(b"ACTIVATE")
            return client.recv(16) == b"OK"
    except OSError:
        return False


@dataclass
class DesktopIpcServer:
    root: Path
    log_file: Path
    on_activate: object
    _thread: threading.Thread | None = None
    _socket: socket.socket | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, name="desktop-ipc", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((LOCAL_HOST, IPC_PORT))
                server.listen(4)
                server.settimeout(0.5)
                self._socket = server
                while not self._stop_event.is_set():
                    try:
                        conn, _ = server.accept()
                    except socket.timeout:
                        continue
                    with conn:
                        message = conn.recv(64)
                        if message == b"ACTIVATE":
                            conn.sendall(b"OK")
                            self.on_activate()
        except OSError as exc:
            append_log(self.log_file, f"Desktop IPC server failed: {exc}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1)


@dataclass
class DesktopShell:
    root: Path
    log_dir: Path
    extra_args: list[str]
    window: object | None = None
    ipc: DesktopIpcServer | None = None
    log_file: Path | None = None

    def activate_window(self) -> None:
        if self.window is None:
            return
        for method_name in ("restore", "show", "focus"):
            method = getattr(self.window, method_name, None)
            if method is None:
                continue
            try:
                method()
            except Exception as exc:
                if self.log_file is not None:
                    append_log(self.log_file, f"Could not activate window using {method_name}: {exc}")

    def on_loaded(self) -> None:
        if self.window is None:
            return
        try:
            current = self.window.get_current_url()
        except Exception:
            current = ""
        if current.startswith(("http://", "https://")) and not current.startswith(ALLOWED_ORIGIN):
            webbrowser.open(current)
            self.window.load_url(ALLOWED_ORIGIN)

    def on_closing(self) -> bool:
        if active_reverse_task_exists(self.root):
            answer = message_box(
                APP_NAME,
                "A reverse prediction task is still running. Close the application and stop the task?",
                yes_no=True,
            )
            if answer != 6:
                return False
        run_stop_script(self.root, self.log_dir)
        if self.ipc is not None:
            self.ipc.stop()
        return True

    def run(self) -> int:
        if send_activation():
            return 0
        if not webview2_runtime_version():
            message_box(
                APP_NAME,
                "Microsoft Edge WebView2 Runtime was not found. Use Browser Mode or install WebView2 Runtime.",
                error=True,
            )
            return 2
        try:
            import webview
        except Exception as exc:
            message_box(APP_NAME, f"Desktop window support could not be loaded: {exc}", error=True)
            return 2

        self.log_file = self.log_dir / "desktop_shell.log"
        self.ipc = DesktopIpcServer(self.root, self.log_file, self.activate_window)
        self.ipc.start()
        self.window = webview.create_window(
            APP_NAME,
            ALLOWED_ORIGIN,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=(MIN_WIDTH, MIN_HEIGHT),
            resizable=True,
            confirm_close=False,
            text_select=True,
            zoomable=True,
        )
        self.window.events.loaded += self.on_loaded
        self.window.events.closing += self.on_closing
        try:
            icon_path = self.root / "resources" / "drug-gradient-chip.ico"
            webview.start(
                gui="edgechromium",
                private_mode=False,
                storage_path=str(self.root / ".runtime" / "webview"),
                icon=str(icon_path) if icon_path.exists() else None,
            )
        finally:
            if self.ipc is not None:
                self.ipc.stop()
        return 0


def browser_mode(root: Path, log_dir: Path, extra_args: list[str]) -> int:
    return run_start_script(root, log_dir, browser=True, extra_args=extra_args)


def desktop_mode(root: Path, log_dir: Path, extra_args: list[str]) -> int:
    marker = root / "runtime" / ".conda-unpacked"
    if (root / "runtime" / "python.exe").exists() and not marker.exists():
        message_box(
            APP_NAME,
            f"{APP_NAME} is preparing its local runtime for first use. This may take several minutes.",
        )
    code = run_start_script(root, log_dir, browser=False, extra_args=extra_args)
    if code != 0:
        message_box(
            APP_NAME,
            f"{APP_NAME} could not start. Exit code: {code}\nLogs: {log_dir}",
            error=True,
        )
        return code
    try:
        return DesktopShell(root, log_dir, extra_args).run()
    except Exception:
        log_file = log_dir / "desktop_shell.log"
        log_exception(log_file, "Desktop shell failed.")
        message_box(APP_NAME, f"Desktop shell failed. Logs: {log_dir}", error=True)
        return 1
