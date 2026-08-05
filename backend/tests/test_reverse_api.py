from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.routes.reverse import get_reverse_task_manager
from app.main import create_app
from app.model_runtime import reverse_tasks
from app.model_runtime.reverse_tasks import ReverseTaskManager
from app.schemas.reverse import ReverseTaskStatusResponse


def reverse_payload() -> dict[str, object]:
    return {
        "inlet1": 0.0,
        "inlet2": 1.0,
        "target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48, 0.58],
    }


def completed_status(task_id: str = "task-1") -> ReverseTaskStatusResponse:
    now = datetime.now(UTC).isoformat()
    return ReverseTaskStatusResponse(
        task_id=task_id,
        status="completed",
        created_at=now,
        started_at=now,
        finished_at=now,
        elapsed_seconds=1.0,
        warnings=["目标浓度包含推荐训练密集范围 [0.10, 0.95] 之外的值，任务仍会运行，但结果需要额外复核。"],
        result={
            "inlet1": 0.0,
            "inlet2": 1.0,
            "target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48, 0.58],
            "chips": [
                {
                    "position": position,
                    "point_labels": [f"P{position * 2 - 1}", f"P{position * 2}"],
                    "chip_type": "5to4",
                    "left_width_mm": 0.261,
                    "right_width_mm": 0.138,
                    "left_bend_class": 5,
                    "right_bend_class": 4,
                    "left_distance_mm": 31.0,
                    "right_distance_mm": 25.0,
                    "target_concentration": 0.1 * position,
                    "predicted_concentration": 0.1 * position + 0.001,
                    "absolute_error": 0.001,
                }
                for position in range(1, 7)
            ],
            "metrics": {
                "mae": 0.001,
                "rmse": 0.001,
                "maxae": 0.001,
                "spearman": 1.0,
                "internal_screening_pass": True,
                "selected_restart": 0,
            },
            "warnings": ["目标浓度包含推荐训练密集范围 [0.10, 0.95] 之外的值，任务仍会运行，但结果需要额外复核。"],
            "notes": [
                "内部筛选只表示结构通过同一 Physics-GNN 代理模型复核。",
                "最终设计仍应使用 Fluent/CFD 独立验证。",
            ],
        },
    )


class FakeReverseTaskManager:
    def __init__(self) -> None:
        self.created = False
        self.status = completed_status()

    def create(self, request: object) -> ReverseTaskStatusResponse:
        self.created = True
        return ReverseTaskStatusResponse(
            task_id="task-1",
            status="running",
            created_at=datetime.now(UTC).isoformat(),
        )

    def get(self, task_id: str) -> ReverseTaskStatusResponse | None:
        if task_id == "missing":
            return None
        return self.status

    def cancel(self, task_id: str) -> ReverseTaskStatusResponse | None:
        if task_id == "missing":
            return None
        if self.status.status == "completed":
            raise RuntimeError("not_cancellable")
        self.status = ReverseTaskStatusResponse(
            task_id=task_id,
            status="cancelled",
            created_at=self.status.created_at,
            finished_at=datetime.now(UTC).isoformat(),
        )
        return self.status


def client_with_manager(manager: FakeReverseTaskManager) -> TestClient:
    app = create_app(load_model=False)
    app.dependency_overrides[get_reverse_task_manager] = lambda: manager
    return TestClient(app)


def test_create_reverse_task_returns_202() -> None:
    manager = FakeReverseTaskManager()
    with client_with_manager(manager) as client:
        response = client.post("/api/v1/reverse-tasks", json=reverse_payload())

    assert response.status_code == 202
    assert response.json() == {"task_id": "task-1", "status": "running"}
    assert manager.created is True


def test_get_completed_reverse_task_returns_result_without_flow_or_paths() -> None:
    with client_with_manager(FakeReverseTaskManager()) as client:
        response = client.get("/api/v1/reverse-tasks/task-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert len(payload["result"]["chips"]) == 6
    assert payload["result"]["metrics"]["internal_screening_pass"] is True
    assert "flow" not in response.text
    assert "checkpoint" not in response.text
    assert "pytorch_geometric-master" not in response.text


def test_reverse_task_busy_returns_409() -> None:
    class BusyManager(FakeReverseTaskManager):
        def create(self, request: object) -> ReverseTaskStatusResponse:
            raise RuntimeError("busy")

    with client_with_manager(BusyManager()) as client:
        response = client.post("/api/v1/reverse-tasks", json=reverse_payload())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVERSE_TASK_BUSY"


def test_cancel_running_reverse_task() -> None:
    manager = FakeReverseTaskManager()
    manager.status = ReverseTaskStatusResponse(
        task_id="task-1",
        status="running",
        created_at=datetime.now(UTC).isoformat(),
        started_at=datetime.now(UTC).isoformat(),
    )

    with client_with_manager(manager) as client:
        response = client.delete("/api/v1/reverse-tasks/task-1")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_completed_reverse_task_is_not_cancellable() -> None:
    with client_with_manager(FakeReverseTaskManager()) as client:
        response = client.delete("/api/v1/reverse-tasks/task-1")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVERSE_TASK_NOT_CANCELLABLE"


def test_unknown_reverse_task_returns_404() -> None:
    with client_with_manager(FakeReverseTaskManager()) as client:
        response = client.get("/api/v1/reverse-tasks/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REVERSE_TASK_NOT_FOUND"


def test_completed_worker_payload_does_not_expose_nested_elapsed_seconds(tmp_path: Path) -> None:
    task_id = "task-1"
    task_dir = tmp_path / task_id
    task_dir.mkdir()
    now = datetime.now(UTC).isoformat()
    (task_dir / "state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task_id": task_id,
                "status": "running",
                "created_at": now,
                "started_at": now,
                "finished_at": None,
                "pid": None,
                "elapsed_seconds": None,
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    result = completed_status(task_id).result
    assert result is not None
    payload_result = result.model_dump()
    payload_result["elapsed_seconds"] = 12.34
    (task_dir / "result.json").write_text(
        json.dumps({"ok": True, "result": payload_result}),
        encoding="utf-8",
    )

    status = ReverseTaskManager(root=tmp_path).get(task_id)

    assert status is not None
    assert status.status == "completed"
    assert status.elapsed_seconds is not None
    assert status.result is not None
    assert "elapsed_seconds" not in status.result.model_dump()


def test_running_reverse_task_timeout_marks_failed_and_kills_worker(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    task_id = "task-timeout"
    started_at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    write_state(
        tmp_path,
        task_id,
        {
            "schema_version": 1,
            "task_id": task_id,
            "status": "running",
            "created_at": started_at,
            "started_at": started_at,
            "finished_at": None,
            "pid": 12345,
            "elapsed_seconds": None,
            "warnings": [],
        },
    )
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(reverse_tasks.subprocess, "run", fake_run)

    status = ReverseTaskManager(root=tmp_path, timeout_seconds=1).get(task_id)

    assert status is not None
    assert status.status == "failed"
    assert status.error is not None
    assert status.error["code"] == "REVERSE_TASK_TIMEOUT"
    assert calls == [["taskkill", "/PID", "12345", "/T", "/F"]]
    state = json.loads((tmp_path / task_id / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["error"]["code"] == "REVERSE_TASK_TIMEOUT"


def test_process_exists_uses_windows_api_without_tasklist(monkeypatch: Any) -> None:
    def fail_tasklist(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("tasklist should not be used on Windows")

    monkeypatch.setattr(reverse_tasks.sys, "platform", "win32")
    monkeypatch.setattr(reverse_tasks.subprocess, "run", fail_tasklist)
    monkeypatch.setattr(reverse_tasks, "_windows_process_exists", lambda pid: pid == 12345)

    assert reverse_tasks.process_exists(12345) is True
    assert reverse_tasks.process_exists(54321) is False


def test_queued_reverse_task_can_be_cancelled_without_worker_pid(tmp_path: Path) -> None:
    task_id = "task-queued"
    now = datetime.now(UTC).isoformat()
    write_state(
        tmp_path,
        task_id,
        {
            "schema_version": 1,
            "task_id": task_id,
            "status": "queued",
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "pid": None,
            "elapsed_seconds": None,
            "warnings": [],
        },
    )

    status = ReverseTaskManager(root=tmp_path, timeout_seconds=1).cancel(task_id)

    assert status is not None
    assert status.status == "cancelled"


def write_state(root: Path, task_id: str, state: dict[str, object]) -> None:
    task_dir = root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
