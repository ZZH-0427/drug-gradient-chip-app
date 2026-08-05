from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import ForwardModelSettings, project_root
from app.schemas.reverse import (
    ReverseDesignRequest,
    ReverseTaskStatusResponse,
)


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
RUNNING_STATUSES = {"queued", "running"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def runtime_root(root: Path | None = None) -> Path:
    return (root or project_root()) / ".runtime" / "reverse_tasks"


def write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def process_exists(pid: int) -> bool:
    if sys.platform == "win32":
        return _windows_process_exists(pid)
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return f'"{pid}"' in completed.stdout or f",{pid}," in completed.stdout


def _windows_process_exists(pid: int) -> bool:
    try:
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            int(pid),
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        error_access_denied = 5
        return ctypes.windll.kernel32.GetLastError() == error_access_denied
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


@dataclass
class ReverseTaskManager:
    root: Path
    timeout_seconds: int = 300

    @classmethod
    def default(cls) -> "ReverseTaskManager":
        return cls(root=runtime_root())

    def create(self, request: ReverseDesignRequest, *, device: str = "cpu") -> ReverseTaskStatusResponse:
        self.root.mkdir(parents=True, exist_ok=True)
        active = self._active_task()
        if active is not None:
            raise RuntimeError("busy")

        settings = ForwardModelSettings.from_env()
        settings.validate_assets()
        task_id = uuid.uuid4().hex
        task_dir = self.root / task_id
        request_path = task_dir / "request.json"
        result_path = task_dir / "result.json"
        state_path = task_dir / "state.json"
        task_dir.mkdir(parents=True, exist_ok=False)
        write_json_atomically(request_path, request.model_dump())

        state: dict[str, Any] = {
            "schema_version": 1,
            "task_id": task_id,
            "status": "queued",
            "created_at": utc_now(),
            "started_at": None,
            "finished_at": None,
            "pid": None,
            "elapsed_seconds": None,
            "warnings": [],
        }
        write_json_atomically(state_path, state)

        args = [
            sys.executable,
            "-m",
            "app.model_runtime.reverse_worker",
            "--request-json",
            str(request_path),
            "--result-json",
            str(result_path),
            "--checkpoint",
            str(settings.checkpoint_path(44)),
            "--device",
            device,
            "--application-root",
            str(project_root()),
        ]
        stdout = task_dir / "worker.stdout.log"
        stderr = task_dir / "worker.stderr.log"
        stdout_handle = stdout.open("w", encoding="utf-8")
        stderr_handle = stderr.open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                args,
                cwd=str(project_root()),
                stdout=stdout_handle,
                stderr=stderr_handle,
            )
        finally:
            stdout_handle.close()
            stderr_handle.close()
        state["status"] = "running"
        state["started_at"] = utc_now()
        state["pid"] = process.pid
        write_json_atomically(state_path, state)
        return self._status_from_state(self._refresh_state(task_id))

    def get(self, task_id: str) -> ReverseTaskStatusResponse | None:
        state_path = self._state_path(task_id)
        if not state_path.exists():
            return None
        return self._status_from_state(self._refresh_state(task_id))

    def cancel(self, task_id: str) -> ReverseTaskStatusResponse | None:
        state_path = self._state_path(task_id)
        if not state_path.exists():
            return None
        state = self._refresh_state(task_id)
        if state["status"] in TERMINAL_STATUSES:
            raise RuntimeError("not_cancellable")
        pid = state.get("pid")
        if isinstance(pid, int):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
        state["status"] = "cancelled"
        state["finished_at"] = utc_now()
        state["elapsed_seconds"] = self._elapsed(state)
        write_json_atomically(state_path, state)
        return self._status_from_state(state)

    def _state_path(self, task_id: str) -> Path:
        return self.root / task_id / "state.json"

    def _result_path(self, task_id: str) -> Path:
        return self.root / task_id / "result.json"

    def _active_task(self) -> dict[str, Any] | None:
        for state_path in self.root.glob("*/state.json"):
            state = self._refresh_state(state_path.parent.name)
            if state["status"] in RUNNING_STATUSES:
                return state
        return None

    def _refresh_state(self, task_id: str) -> dict[str, Any]:
        state_path = self._state_path(task_id)
        state = read_json(state_path)
        if state["status"] in TERMINAL_STATUSES:
            return state

        result_path = self._result_path(task_id)
        if result_path.exists():
            payload = read_json(result_path)
            state["finished_at"] = utc_now()
            state["elapsed_seconds"] = self._elapsed(state)
            if payload.get("ok"):
                result = dict(payload["result"])
                result.pop("elapsed_seconds", None)
                state["status"] = "completed"
                state["result"] = result
                state["warnings"] = result.get("warnings", [])
            else:
                state["status"] = "failed"
                state["error"] = _safe_error(payload.get("error"))
            write_json_atomically(state_path, state)
            return state

        if self._elapsed(state) is not None and self._elapsed(state) > self.timeout_seconds:
            pid = state.get("pid")
            if isinstance(pid, int):
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
            state["status"] = "failed"
            state["finished_at"] = utc_now()
            state["elapsed_seconds"] = self._elapsed(state)
            state["error"] = {
                "code": "REVERSE_TASK_TIMEOUT",
                "message": "反向设计任务超时。",
            }
            write_json_atomically(state_path, state)
            return state

        pid = state.get("pid")
        if isinstance(pid, int) and not process_exists(pid):
            state["status"] = "failed"
            state["finished_at"] = utc_now()
            state["elapsed_seconds"] = self._elapsed(state)
            state["error"] = {
                "code": "REVERSE_TASK_FAILED",
                "message": "反向设计任务提前退出。",
            }
            write_json_atomically(state_path, state)
        return state

    def _elapsed(self, state: dict[str, Any]) -> float | None:
        started_at = state.get("started_at")
        if not started_at:
            return None
        started = datetime.fromisoformat(str(started_at))
        end_raw = state.get("finished_at")
        end = datetime.fromisoformat(str(end_raw)) if end_raw else datetime.now(UTC)
        return max(0.0, (end - started).total_seconds())

    def _status_from_state(self, state: dict[str, Any]) -> ReverseTaskStatusResponse:
        return ReverseTaskStatusResponse(
            task_id=state["task_id"],
            status=state["status"],
            created_at=state["created_at"],
            started_at=state.get("started_at"),
            finished_at=state.get("finished_at"),
            elapsed_seconds=state.get("elapsed_seconds"),
            result=state.get("result"),
            error=state.get("error"),
            warnings=state.get("warnings", []),
        )


def _safe_error(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "code": str(value.get("code", "REVERSE_TASK_FAILED")),
            "message": str(value.get("message", "反向设计任务失败。")),
        }
    return {"code": "REVERSE_TASK_FAILED", "message": "反向设计任务失败。"}
