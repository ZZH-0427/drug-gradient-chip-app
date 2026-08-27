from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.chat.schemas import ChatMessageRequest
from app.chat.service import ChatService
from app.chat.session import ChipDraft, ConversationSessionStore
from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.model_runtime import reverse_tasks
from app.model_runtime import reverse_worker
from app.model_runtime.reverse_tasks import ReverseTaskManager
from app.schemas.forward import ForwardPredictionItem, ForwardPredictionResponse
from app.schemas.reverse import ReverseTaskCreatedResponse


class FakeForwardAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self.requests = []

    def predict(self, request):
        self.calls += 1
        self.requests.append(request)
        return ForwardPredictionResponse(
            sample_name=request.sample_name,
            inlets={"inlet1": float(request.inlet1), "inlet2": float(request.inlet2)},
            chip_count=request.chip_count,
            predictions=[
                ForwardPredictionItem(
                    position=index,
                    point=f"y{index}",
                    chip_type=chip.chip_type,
                    concentration=float(index) / 10.0,
                )
                for index, chip in enumerate(request.chips_by_position(), start=1)
            ],
        )


class FailingForwardAdapter(FakeForwardAdapter):
    def predict(self, request):
        raise ModelRuntimeError(ModelErrorCode.MODEL_INFERENCE_FAILED, r"C:\secret\checkpoint.pt")


class FakeReverseTaskManager:
    def __init__(self) -> None:
        self.calls = 0
        self.cancel_calls = 0
        self.requests = []
        self.cancel_status = ReverseTaskCreatedResponse(task_id="task-1", status="cancelled")

    def create(self, request):
        self.calls += 1
        self.requests.append(request)
        return ReverseTaskCreatedResponse(task_id="task-1", status="running")

    def cancel(self, task_id):
        self.cancel_calls += 1
        return ReverseTaskCreatedResponse(task_id=task_id, status=self.cancel_status.status)


def request(message: str, session_id: str | None = None, language: str = "zh-CN") -> ChatMessageRequest:
    return ChatMessageRequest(session_id=session_id, message=message, language=language)


def zh(text: str) -> str:
    return text.encode("ascii").decode("unicode_escape")


def make_service(
    *,
    store: ConversationSessionStore | None = None,
    adapter: FakeForwardAdapter | None = None,
    reverse_manager: FakeReverseTaskManager | None = None,
) -> ChatService:
    return ChatService(
        sessions=store or ConversationSessionStore(),
        forward_adapter=adapter,
        reverse_manager=reverse_manager,
    )


def assert_chip(
    chip: dict,
    *,
    chip_type: str,
    left_width: float,
    right_width: float,
    left_distance: float,
    right_distance: float,
) -> None:
    assert chip["chip_type"] == chip_type
    assert chip["left_width_mm"] == left_width
    assert chip["right_width_mm"] == right_width
    assert chip["left_bend_straight_distance_mm"] == left_distance
    assert chip["right_bend_straight_distance_mm"] == right_distance


def fake_reverse_result(
    *,
    inlet1: float,
    inlet2: float,
    target_concentrations: list[float],
    mae: float,
    rmse: float | None = None,
    maxae: float | None = None,
    spearman: float = 0.99,
    screening_pass: bool = True,
) -> dict[str, Any]:
    return {
        "inlet1": inlet1,
        "inlet2": inlet2,
        "target_concentrations": list(target_concentrations),
        "chips": [],
        "metrics": {
            "mae": mae,
            "rmse": mae if rmse is None else rmse,
            "maxae": mae if maxae is None else maxae,
            "spearman": spearman,
            "internal_screening_pass": screening_pass,
            "selected_restart": 0,
        },
        "warnings": [],
        "notes": [],
    }


def fill_complete_forward_session(store: ConversationSessionStore) -> str:
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.state = "ready_for_confirmation"
    session.pending_confirmation = "forward"
    draft = session.forward_draft
    draft.set_chip_count(6)
    draft.inlet1 = 1.0
    draft.inlet2 = 0.0
    for position in range(1, 7):
        draft.chips[position] = ChipDraft(
            position=position,
            chip_type="5to4",
            left_width_mm=0.1,
            right_width_mm=0.2,
            left_bend_straight_distance_mm=10.0 + position,
            right_bend_straight_distance_mm=20.0 + position,
        )
    return session.session_id


def fill_complete_reverse_session(store: ConversationSessionStore) -> str:
    session = store.create("zh-CN")
    session.active_mode = "reverse"
    session.state = "ready_for_confirmation"
    session.pending_confirmation = "reverse"
    session.reverse_draft.inlet1 = 0.0
    session.reverse_draft.inlet2 = 1.0
    session.reverse_draft.target_concentrations = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    return session.session_id


def test_incomplete_forward_does_not_call_adapter() -> None:
    adapter = FakeForwardAdapter()
    service = make_service(adapter=adapter)

    response = service.handle_message(request(zh(r"\u505a6\u82af\u7247\u6b63\u5411\u9884\u6d4b")))

    assert response.state == "collecting"
    assert "inlet" in response.missing_fields
    assert adapter.calls == 0


def test_ambiguous_request_does_not_call_adapter_or_mutate_state() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    adapter = FakeForwardAdapter()
    service = make_service(store=store, adapter=adapter)

    response = service.handle_message(request(zh(r"\u7b2c\u4e09\u4e2a\u82af\u7247\u6539\u62100.2"), session.session_id))

    assert response.error is not None
    assert response.error.code == "AMBIGUOUS_INPUT"
    assert store.get(session.session_id).forward_draft.chips[3].left_width_mm is None
    assert adapter.calls == 0


def test_complete_but_unconfirmed_forward_does_not_call_adapter() -> None:
    store = ConversationSessionStore()
    session_id = fill_complete_forward_session(store)
    session = store.get(session_id)
    assert session is not None
    session.pending_confirmation = None
    adapter = FakeForwardAdapter()
    service = make_service(store=store, adapter=adapter)

    response = service.handle_message(request("show parameters", session_id))

    assert response.forward_prediction is None
    assert adapter.calls == 0


def test_confirmed_complete_forward_calls_fake_adapter_once() -> None:
    store = ConversationSessionStore()
    session_id = fill_complete_forward_session(store)
    adapter = FakeForwardAdapter()
    service = make_service(store=store, adapter=adapter)

    response = service.handle_message(request(zh(r"\u786e\u8ba4"), session_id))

    assert response.state == "completed"
    assert adapter.calls == 1
    assert response.forward_prediction is not None
    assert response.forward_prediction.predictions[0].concentration == 0.1


def test_complete_reverse_calls_fake_task_manager_once() -> None:
    store = ConversationSessionStore()
    session_id = fill_complete_reverse_session(store)
    manager = FakeReverseTaskManager()
    service = make_service(store=store, reverse_manager=manager)

    response = service.handle_message(request("run", session_id))

    assert response.state == "running"
    assert manager.calls == 1
    assert response.reverse_task is not None
    assert response.reverse_task.task_id == "task-1"


def test_reverse_targets_without_inlet_remain_collecting() -> None:
    manager = FakeReverseTaskManager()
    service = make_service(reverse_manager=manager)

    response = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b "
                r"\u76ee\u6807\u6d53\u5ea6\uff1a0.08 0.14 0.25 0.38 0.48 0.58"
            )
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.confirmation is None
    assert response.missing_fields == ["inlet"]
    assert response.parameter_summary["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]
    assert response.parameter_summary["inlet1"] is None
    assert response.parameter_summary["inlet2"] is None
    session = service.sessions.get(response.session_id)
    assert session is not None
    assert session.reverse_draft.inlet1 is None
    assert session.reverse_draft.inlet2 is None
    assert manager.calls == 0


def test_reverse_targets_with_dunhao_and_sentence_period_require_inlet() -> None:
    service = make_service(reverse_manager=FakeReverseTaskManager())

    response = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b\uff0c"
                r"\u76ee\u6807\u6d53\u5ea6\u662f 0.08\u3001.14\u3001.25\u3001.38\u3001.48\u3001.58\u3002"
            )
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.confirmation is None
    assert response.missing_fields == ["inlet"]
    assert response.parameter_summary["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_active_reverse_accepts_target_phrase_without_new_reverse_keyword() -> None:
    service = make_service(reverse_manager=FakeReverseTaskManager())

    initial = service.handle_message(request(zh(r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b")))
    response = service.handle_message(
        request(
            zh(r"\u76ee\u6807\u6d53\u5ea6\u662f 0.08\u3001.14\u3001.25\u3001.38\u3001.48\u3001.58\u3002"),
            initial.session_id,
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.confirmation is None
    assert response.missing_fields == ["inlet"]
    assert response.parameter_summary["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_reverse_targets_ignore_fixed_position_count_before_target_anchor() -> None:
    service = make_service(reverse_manager=FakeReverseTaskManager())

    response = service.handle_message(
        request(
            zh(
                r"\u5e2e\u6211\u505a\u4e00\u4e0b\u53cd\u5411\u9884\u6d4b\uff0c"
                r"\u6211\u5e0c\u671b6\u4e2a\u4f4d\u7f6e\u7684"
                r"\u76ee\u6807\u6d53\u5ea6\u5206\u522b\u662f.08\u3001.14\u3001.25\u3001.38\u3001.48\u548c.58\u3002"
            )
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.confirmation is None
    assert response.missing_fields == ["inlet"]
    assert response.parameter_summary["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]
    assert 6.0 not in response.parameter_summary["target_concentrations"]


def test_reverse_multiline_targets_require_inlet() -> None:
    service = make_service(reverse_manager=FakeReverseTaskManager())

    response = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b\n"
                r"\u76ee\u6807\u6d53\u5ea6\uff1a\n"
                r"0.08\n0.14\n0.25\n0.38\n0.48\n0.58"
            )
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.confirmation is None
    assert response.missing_fields == ["inlet"]
    assert response.parameter_summary["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]
    assert response.parameter_summary["inlet1"] is None
    assert response.parameter_summary["inlet2"] is None


def test_five_reverse_targets_remain_collecting_without_model_call() -> None:
    manager = FakeReverseTaskManager()
    service = make_service(reverse_manager=manager)

    response = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b\n"
                r"\u76ee\u6807\u6d53\u5ea6\uff1a\n"
                r"0.08\n0.14\n0.25\n0.38\n0.48"
            )
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.confirmation is None
    assert response.missing_fields == ["inlet", "target_concentrations"]
    assert manager.calls == 0


def test_seven_reverse_targets_are_not_truncated_to_first_six() -> None:
    manager = FakeReverseTaskManager()
    service = make_service(reverse_manager=manager)

    response = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b\uff0c"
                r"\u76ee\u6807\u6d53\u5ea6\u662f0.08 0.14 0.25 0.38 0.48 0.58 0.63"
            )
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.confirmation is None
    assert response.missing_fields == ["inlet", "target_concentrations"]
    assert response.parameter_summary["target_concentrations"] == []
    assert manager.calls == 0


def test_malformed_reverse_target_token_is_not_accepted_as_complete_request() -> None:
    manager = FakeReverseTaskManager()
    service = make_service(reverse_manager=manager)

    response = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b\uff0c"
                r"\u76ee\u6807\u6d53\u5ea6\u662f1.2.3 0.1 0.2 0.3 0.4 0.5"
            )
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.confirmation is None
    assert response.missing_fields == ["inlet", "target_concentrations"]
    assert response.parameter_summary["target_concentrations"] == []
    assert manager.calls == 0


def test_confirmed_reverse_uses_user_selected_inlet_for_task_creation() -> None:
    manager = FakeReverseTaskManager()
    service = make_service(reverse_manager=manager)

    ready = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b "
                r"\u5165\u53e31\u9ad8\u6d53\u5ea6 "
                r"\u76ee\u6807\u6d53\u5ea6\uff1a0.08 0.14 0.25 0.38 0.48 0.58"
            )
        )
    )
    response = service.handle_message(request(zh(r"\u786e\u8ba4"), ready.session_id))

    assert response.error is None
    assert response.state == "running"
    assert manager.calls == 1
    created_request = manager.requests[0]
    assert created_request.inlet1 == 1.0
    assert created_request.inlet2 == 0.0
    assert created_request.target_concentrations == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_confirmed_reverse_uses_inlet2_high_for_task_creation() -> None:
    manager = FakeReverseTaskManager()
    service = make_service(reverse_manager=manager)

    ready = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b "
                r"\u5165\u53e32\u9ad8\u6d53\u5ea6 "
                r"\u76ee\u6807\u6d53\u5ea6\uff1a0.08 0.14 0.25 0.38 0.48 0.58"
            )
        )
    )
    response = service.handle_message(request(zh(r"\u786e\u8ba4"), ready.session_id))

    assert response.error is None
    assert response.state == "running"
    assert manager.calls == 1
    created_request = manager.requests[0]
    assert created_request.inlet1 == 0.0
    assert created_request.inlet2 == 1.0
    assert created_request.target_concentrations == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_reverse_installed_smoke_creates_real_task_with_user_selected_inlet(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    class FakeSettings:
        def validate_assets(self) -> None:
            return None

        def checkpoint_path(self, seed: int) -> Path:
            assert seed == 44
            return tmp_path / "checkpoint.pt"

    class FakeProcess:
        pid = 24680

    captured: dict[str, Any] = {}

    def fake_popen(args: list[str], **kwargs: object) -> FakeProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(reverse_tasks.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(reverse_tasks, "project_root", lambda: tmp_path)
    monkeypatch.setattr(reverse_tasks, "process_exists", lambda pid: pid == FakeProcess.pid)
    monkeypatch.setattr(reverse_tasks.ForwardModelSettings, "from_env", staticmethod(lambda: FakeSettings()))

    manager = ReverseTaskManager(root=tmp_path / "tasks")
    service = make_service(reverse_manager=manager)
    ready = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b "
                r"\u5165\u53e31\u9ad8\u6d53\u5ea6 "
                r"\u76ee\u6807\u6d53\u5ea6\uff1a0.08 0.14 0.25 0.38 0.48 0.58"
            )
        )
    )
    response = service.handle_message(request(zh(r"\u786e\u8ba4"), ready.session_id))

    assert response.error is None
    assert response.state == "running"
    assert response.reverse_task is not None
    assert response.reverse_task.status == "running"
    assert response.reverse_task.task_id
    request_path = tmp_path / "tasks" / response.reverse_task.task_id / "request.json"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload == {
        "inlet1": 1.0,
        "inlet2": 0.0,
        "target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48, 0.58],
    }
    assert captured["args"][1:3] == ["-m", "app.model_runtime.reverse_worker"]
    assert captured["kwargs"]["shell"] is False
    calls: list[dict[str, Any]] = []

    def fake_run_reverse_design(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return fake_reverse_result(
            inlet1=float(kwargs["inlet1"]),
            inlet2=float(kwargs["inlet2"]),
            target_concentrations=list(kwargs["target_concentrations"]),
            mae=0.01,
        )

    result_path = tmp_path / "tasks" / response.reverse_task.task_id / "result.json"
    monkeypatch.setattr(reverse_worker, "run_reverse_design", fake_run_reverse_design)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reverse_worker",
            "--request-json",
            str(request_path),
            "--result-json",
            str(result_path),
            "--checkpoint",
            str(tmp_path / "checkpoint.pt"),
            "--device",
            "cpu",
            "--application-root",
            str(tmp_path),
        ],
    )

    reverse_worker.main()

    assert [(call["inlet1"], call["inlet2"]) for call in calls] == [(1.0, 0.0)]
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_payload["ok"] is True
    assert result_payload["result"]["inlet1"] == 1.0
    assert result_payload["result"]["inlet2"] == 0.0


def test_legacy_reverse_worker_request_runs_only_specified_inlet(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(
        json.dumps(
            {
                "inlet1": 1.0,
                "inlet2": 0.0,
                "target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48, 0.58],
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []

    def fake_run_reverse_design(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return fake_reverse_result(
            inlet1=float(kwargs["inlet1"]),
            inlet2=float(kwargs["inlet2"]),
            target_concentrations=list(kwargs["target_concentrations"]),
            mae=0.01,
        )

    monkeypatch.setattr(reverse_worker, "run_reverse_design", fake_run_reverse_design)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reverse_worker",
            "--request-json",
            str(request_path),
            "--result-json",
            str(result_path),
            "--checkpoint",
            str(tmp_path / "checkpoint.pt"),
            "--device",
            "cpu",
            "--application-root",
            str(tmp_path),
        ],
    )

    reverse_worker.main()

    assert [(call["inlet1"], call["inlet2"]) for call in calls] == [(1.0, 0.0)]
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_payload["ok"] is True
    assert result_payload["result"]["inlet1"] == 1.0
    assert result_payload["result"]["inlet2"] == 0.0


def test_reverse_worker_request_runs_only_specified_inlet2(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(
        json.dumps(
            {
                "inlet1": 0.0,
                "inlet2": 1.0,
                "target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48, 0.58],
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []

    def fake_run_reverse_design(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return fake_reverse_result(
            inlet1=float(kwargs["inlet1"]),
            inlet2=float(kwargs["inlet2"]),
            target_concentrations=list(kwargs["target_concentrations"]),
            mae=0.01,
        )

    monkeypatch.setattr(reverse_worker, "run_reverse_design", fake_run_reverse_design)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reverse_worker",
            "--request-json",
            str(request_path),
            "--result-json",
            str(result_path),
            "--checkpoint",
            str(tmp_path / "checkpoint.pt"),
            "--device",
            "cpu",
            "--application-root",
            str(tmp_path),
        ],
    )

    reverse_worker.main()

    assert [(call["inlet1"], call["inlet2"]) for call in calls] == [(0.0, 1.0)]
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_payload["ok"] is True
    assert result_payload["result"]["inlet1"] == 0.0
    assert result_payload["result"]["inlet2"] == 1.0


def test_reverse_worker_rejects_malformed_requests_without_optimizer_call(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run_reverse_design(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(reverse_worker, "run_reverse_design", fake_run_reverse_design)
    malformed_requests = [
        {"inlet1": 1.0, "target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]},
        {"inlet2": 0.0, "target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]},
        {},
        {"target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]},
        {"target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48]},
        {"target_concentrations": [0.08, 0.14, 0.25, 0.38, 0.48, 0.58, 0.63]},
    ]

    for malformed_request in malformed_requests:
        try:
            reverse_worker.run_reverse_request(
                malformed_request,
                device="cpu",
                checkpoint_path=Path("checkpoint.pt"),
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"Malformed request unexpectedly succeeded: {malformed_request}")

    assert calls == []


def test_incomplete_reverse_targets_and_missing_inlet_do_not_reach_confirmation() -> None:
    service = make_service(reverse_manager=FakeReverseTaskManager())

    response = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b\n"
                r"\u76ee\u6807\u6d53\u5ea6\uff1a\n"
                r"0.08\n0.14\n0.25"
            )
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.confirmation is None
    assert response.missing_fields == ["inlet", "target_concentrations"]


def test_switching_from_forward_to_reverse_does_not_inherit_forward_inlet() -> None:
    store = ConversationSessionStore()
    service = make_service(store=store, adapter=FakeForwardAdapter(), reverse_manager=FakeReverseTaskManager())

    forward = service.handle_message(
        request(
            zh(
                r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b\uff0c"
                r"\u5165\u53e31\u9ad8\u6d53\u5ea6"
            )
        )
    )
    reverse = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b "
                r"\u76ee\u6807\u6d53\u5ea6\uff1a0.08 0.14 0.25 0.38 0.48 0.58"
            ),
            forward.session_id,
        )
    )

    session = store.get(forward.session_id)
    assert session is not None
    assert session.forward_draft.inlet1 == 1.0
    assert session.forward_draft.inlet2 == 0.0
    assert session.reverse_draft.inlet1 is None
    assert session.reverse_draft.inlet2 is None
    assert reverse.error is None
    assert reverse.state == "collecting"
    assert reverse.missing_fields == ["inlet"]


def test_one_turn_reverse_with_inlet1_high_and_targets_reaches_confirmation() -> None:
    service = make_service(reverse_manager=FakeReverseTaskManager())

    response = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b\uff0c"
                r"\u5165\u53e31\u9ad8\u6d53\u5ea6\uff0c"
                r"\u76ee\u6807\u6d53\u5ea6\u662f.08\u3001.14\u3001.25\u3001.38\u3001.48\u3001.58\u3002"
            )
        )
    )

    assert response.error is None
    assert response.state == "ready_for_confirmation"
    assert response.confirmation is not None
    assert response.confirmation.mode == "reverse"
    assert response.missing_fields == []
    assert response.parameter_summary["inlet1"] == 1.0
    assert response.parameter_summary["inlet2"] == 0.0
    assert response.parameter_summary["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_one_turn_reverse_with_inlet2_high_and_targets_reaches_confirmation() -> None:
    service = make_service(reverse_manager=FakeReverseTaskManager())

    response = service.handle_message(
        request(
            zh(
                r"\u505a\u53cd\u5411\u9884\u6d4b\uff0c"
                r"\u5165\u53e32\u9ad8\u6d53\u5ea6\uff0c"
                r"\u76ee\u6807\u6d53\u5ea6\u662f.08\u3001.14\u3001.25\u3001.38\u3001.48\u3001.58\u3002"
            )
        )
    )

    assert response.error is None
    assert response.state == "ready_for_confirmation"
    assert response.parameter_summary["inlet1"] == 0.0
    assert response.parameter_summary["inlet2"] == 1.0
    assert response.parameter_summary["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_reverse_targets_first_then_inlet_reaches_confirmation() -> None:
    service = make_service(reverse_manager=FakeReverseTaskManager())
    targets = service.handle_message(
        request(
            zh(
                r"\u8fdb\u884c\u53cd\u5411\u9884\u6d4b\uff0c"
                r"\u76ee\u6807\u6d53\u5ea6\u662f0.08\u3001.14\u3001.25\u3001.38\u3001.48\u3001.58\u3002"
            )
        )
    )

    response = service.handle_message(request(zh(r"\u5165\u53e31\u9ad8\u6d53\u5ea6"), targets.session_id))

    assert targets.state == "collecting"
    assert targets.missing_fields == ["inlet"]
    assert response.error is None
    assert response.state == "ready_for_confirmation"
    assert response.parameter_summary["inlet1"] == 1.0
    assert response.parameter_summary["inlet2"] == 0.0
    assert response.parameter_summary["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_reverse_inlet_first_then_targets_reaches_confirmation() -> None:
    service = make_service(reverse_manager=FakeReverseTaskManager())
    inlet = service.handle_message(request(zh(r"\u505a\u53cd\u5411\u9884\u6d4b\uff0c\u5165\u53e32\u9ad8\u6d53\u5ea6")))

    response = service.handle_message(
        request(
            zh(r"\u76ee\u6807\u6d53\u5ea6\u662f.08\u3001.14\u3001.25\u3001.38\u3001.48\u3001.58\u3002"),
            inlet.session_id,
        )
    )

    assert inlet.state == "collecting"
    assert inlet.missing_fields == ["target_concentrations"]
    assert response.error is None
    assert response.state == "ready_for_confirmation"
    assert response.parameter_summary["inlet1"] == 0.0
    assert response.parameter_summary["inlet2"] == 1.0
    assert response.parameter_summary["target_concentrations"] == [0.08, 0.14, 0.25, 0.38, 0.48, 0.58]


def test_reverse_conflicting_inlets_are_rejected_without_partial_mutation() -> None:
    store = ConversationSessionStore()
    service = make_service(store=store, reverse_manager=FakeReverseTaskManager())
    initial = service.handle_message(request(zh(r"\u505a\u53cd\u5411\u9884\u6d4b\uff0c\u5165\u53e31\u9ad8\u6d53\u5ea6")))
    before = store.get(initial.session_id).reverse_draft.summary()

    response = service.handle_message(
        request(
            zh(r"\u5165\u53e31\u9ad8\u6d53\u5ea6\uff0c\u5165\u53e32\u9ad8\u6d53\u5ea6"),
            initial.session_id,
        )
    )

    assert response.error is not None
    assert response.error.code == "AMBIGUOUS_INPUT"
    assert store.get(initial.session_id).reverse_draft.summary() == before


def test_forward_still_requires_inlet_after_reverse_contract_change() -> None:
    adapter = FakeForwardAdapter()
    service = make_service(adapter=adapter, reverse_manager=FakeReverseTaskManager())

    response = service.handle_message(request(zh(r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b")))

    assert response.state == "collecting"
    assert "inlet" in response.missing_fields
    assert adapter.calls == 0


def test_reset_clears_draft() -> None:
    store = ConversationSessionStore()
    session_id = fill_complete_forward_session(store)
    service = make_service(store=store)

    response = service.handle_message(request("reset", session_id))

    assert response.state == "idle"
    assert store.get(session_id).forward_draft.chip_count is None


def test_model_error_becomes_safe_chat_error() -> None:
    store = ConversationSessionStore()
    session_id = fill_complete_forward_session(store)
    service = make_service(store=store, adapter=FailingForwardAdapter())

    response = service.handle_message(request("run", session_id))

    assert response.error is not None
    assert response.error.code == "MODEL_RUNTIME_ERROR"
    assert "checkpoint" not in response.model_dump_json()
    assert "C:\\" not in response.model_dump_json()


def test_forward_p_values_update_draft_without_calling_adapter() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    adapter = FakeForwardAdapter()
    service = make_service(store=store, adapter=adapter)

    response = service.handle_message(request("P1 0.12 P2=0.18", session.session_id))

    chip = store.get(session.session_id).forward_draft.chips[1]
    assert chip.left_width_mm == 0.12
    assert chip.right_width_mm == 0.18
    assert response.state == "collecting"
    assert adapter.calls == 0


def test_forward_multi_turn_natural_language_reaches_confirmation_before_model_call() -> None:
    adapter = FakeForwardAdapter()
    service = make_service(adapter=adapter)
    session_id = None

    messages = [
        "use 6 chips for forward prediction",
        "inlet 1 high",
    ]
    for position in range(1, 7):
        messages.extend(
            [
                f"set chip {position} chip type to 5to4",
                f"P{position * 2 - 1} 0.10 P{position * 2} 0.20",
                f"set chip {position} left distance to {10 + position}",
                f"set chip {position} right distance to {20 + position}",
            ]
        )

    response = None
    for text in messages:
        response = service.handle_message(request(text, session_id, "en"))
        session_id = response.session_id
        assert adapter.calls == 0

    assert response is not None
    assert response.state == "ready_for_confirmation"
    assert response.confirmation is not None
    assert response.confirmation.summary["sample_name"] == "chat-forward"
    assert adapter.calls == 0

    completed = service.handle_message(request("confirm", session_id, "en"))

    assert completed.state == "completed"
    assert adapter.calls == 1
    assert adapter.requests[0].chip_count == 6


def test_chinese_chip_type_updates_draft() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    response = service.handle_message(request(zh(r"\u7b2c\u4e00\u4e2a\u82af\u7247\u7c7b\u578b\u4e3a5to4"), session.session_id))

    assert response.error is None
    assert store.get(session.session_id).forward_draft.chips[1].chip_type == "5to4"


def test_chinese_ordinal_chip_fields_do_not_change_chip_count_and_update_draft() -> None:
    store = ConversationSessionStore()
    service = make_service(store=store)

    response = service.handle_message(request(zh(r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b")))
    session_id = response.session_id
    assert response.parameter_summary["chip_count"] == 6

    response = service.handle_message(request(zh(r"\u7b2c1\u4e2a\u82af\u7247\u53f3\u5bbd\u5ea6\u662f.138"), session_id))
    draft = store.get(session_id).forward_draft
    assert response.error is None
    assert response.parameter_summary["chip_count"] == 6
    assert draft.chip_count == 6
    assert draft.chips[1].right_width_mm == 0.138
    assert "chips.1.right_width_mm" not in response.missing_fields

    response = service.handle_message(request(zh(r"\u7b2c2\u4e2a\u82af\u7247\u5de6\u5bbd\u5ea6\u662f.1"), session_id))
    assert response.error is None
    assert response.parameter_summary["chip_count"] == 6
    assert draft.chip_count == 6
    assert draft.chips[2].left_width_mm == 0.1

    response = service.handle_message(request(zh(r"\u7b2c6\u4e2a\u82af\u7247\u7c7b\u578b\u662f3to1"), session_id))
    assert response.error is None
    assert response.parameter_summary["chip_count"] == 6
    assert draft.chip_count == 6
    assert draft.chips[6].chip_type == "3to1"


def test_english_chip_type_updates_draft() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    response = service.handle_message(request("set chip 2 chip type to 4to5", session.session_id, "en"))

    assert response.error is None
    assert store.get(session.session_id).forward_draft.chips[2].chip_type == "4to5"


def test_chinese_left_and_right_distances_update_draft() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    response = service.handle_message(
        request(zh(r"\u7b2c\u4e00\u4e2a\u82af\u7247\u5de6\u8ddd\u79bb31\uff0c\u53f3\u8ddd\u79bb25"), session.session_id)
    )

    chip = store.get(session.session_id).forward_draft.chips[1]
    assert response.error is None
    assert chip.left_bend_straight_distance_mm == 31.0
    assert chip.right_bend_straight_distance_mm == 25.0


def test_chinese_single_distance_fields_update_draft() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    left = service.handle_message(
        request(zh(r"\u7b2c1\u4e2a\u82af\u7247\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f31"), session.session_id)
    )
    right = service.handle_message(
        request(zh(r"\u7b2c3\u4e2a\u82af\u7247\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f25"), session.session_id)
    )

    draft = store.get(session.session_id).forward_draft
    assert left.error is None
    assert right.error is None
    assert draft.chip_count == 6
    assert draft.chips[1].left_bend_straight_distance_mm == 31.0
    assert draft.chips[3].right_bend_straight_distance_mm == 25.0


def test_english_left_and_right_distances_update_draft() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    response = service.handle_message(
        request("set chip 3 left distance to 31 and right distance to 25", session.session_id, "en")
    )

    chip = store.get(session.session_id).forward_draft.chips[3]
    assert response.error is None
    assert chip.left_bend_straight_distance_mm == 31.0
    assert chip.right_bend_straight_distance_mm == 25.0


def test_four_chips_accepts_p8() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(4)
    service = make_service(store=store)

    response = service.handle_message(request("P8 0.18", session.session_id, "en"))

    assert response.error is None
    assert store.get(session.session_id).forward_draft.chips[4].right_width_mm == 0.18


def test_four_chips_rejects_p9_without_mutating_draft() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(4)
    before = session.forward_draft.summary()
    service = make_service(store=store)

    response = service.handle_message(request("P9 0.18", session.session_id, "en"))

    assert response.error is not None
    assert response.error.code == "P_INDEX_OUT_OF_RANGE"
    assert store.get(session.session_id).forward_draft.summary() == before


def test_four_chips_rejects_out_of_range_chinese_ordinal_without_changing_chip_count() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(4)
    before = session.forward_draft.summary()
    service = make_service(store=store)

    response = service.handle_message(request(zh(r"\u7b2c5\u4e2a\u82af\u7247\u5de6\u5bbd\u5ea6\u662f.1"), session.session_id))

    draft = store.get(session.session_id).forward_draft
    assert response.error is not None
    assert response.error.code == "CHIP_INDEX_OUT_OF_RANGE"
    assert draft.chip_count == 4
    assert draft.summary() == before


def test_unknown_chip_count_rejects_p_values_without_saving_draft() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    service = make_service(store=store)

    response = service.handle_message(request("P1 0.12", session.session_id, "en"))

    assert response.error is not None
    assert response.error.code == "CHIP_COUNT_REQUIRED"
    assert store.get(session.session_id).forward_draft.chips == {}


def test_no_position_chinese_field_remains_ambiguous_without_mutation() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    before = session.forward_draft.summary()
    service = make_service(store=store)

    response = service.handle_message(request(zh(r"\u53f3\u5bbd\u5ea6\u662f0.138"), session.session_id))

    assert response.error is not None
    assert response.error.code == "AMBIGUOUS_INPUT"
    assert store.get(session.session_id).forward_draft.summary() == before


def test_composite_buildtest5_prompt_collects_forward_chip_and_inlet_fields() -> None:
    adapter = FakeForwardAdapter()
    service = make_service(adapter=adapter)

    response = service.handle_message(
        request(
            zh(
                r"\u8bf7\u5e2e\u6211\u8fdb\u884c6\u4e2a\u82af\u7247\u7684\u6b63\u5411\u9884\u6d4b"
                r"\uff0c\u5165\u53e31\u9ad8\u6d53\u5ea6\u3002"
                r"\u7b2c1\u4e2a\u82af\u7247\u7c7b\u578b\u662f5to4\uff0c"
                r"\u7b2c1\u4e2a\u82af\u7247\u5de6\u5bbd\u5ea6\u662f.261\uff0c"
                r"\u7b2c1\u4e2a\u82af\u7247\u53f3\u5bbd\u5ea6\u662f.138\uff0c"
                r"\u7b2c1\u4e2a\u82af\u7247\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f31\uff0c"
                r"\u7b2c1\u4e2a\u82af\u7247\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f25\u3002"
            )
        )
    )

    assert response.error is None
    assert response.state == "collecting"
    assert response.forward_prediction is None
    assert adapter.calls == 0
    assert response.parameter_summary["chip_count"] == 6
    assert response.parameter_summary["inlet1"] == 1.0
    assert response.parameter_summary["inlet2"] == 0.0
    chip = response.parameter_summary["chips"][0]
    assert chip["chip_type"] == "5to4"
    assert chip["left_width_mm"] == 0.261
    assert chip["right_width_mm"] == 0.138
    assert chip["left_bend_straight_distance_mm"] == 31.0
    assert chip["right_bend_straight_distance_mm"] == 25.0
    assert "chips.2.chip_type" in response.missing_fields


def test_consistent_dual_inlet_composite_relations_are_accepted() -> None:
    service = make_service()

    high_low = service.handle_message(
        request(
            zh(
                r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b\uff0c"
                r"\u5165\u53e31\u9ad8\u6d53\u5ea6\uff0c\u5165\u53e32\u4f4e\u6d53\u5ea6"
            )
        )
    )
    low_high = service.handle_message(
        request(
            zh(
                r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b\uff0c"
                r"\u5165\u53e31\u4f4e\u6d53\u5ea6\uff0c\u5165\u53e32\u9ad8\u6d53\u5ea6"
            )
        )
    )

    assert high_low.error is None
    assert high_low.parameter_summary["chip_count"] == 6
    assert high_low.parameter_summary["inlet1"] == 1.0
    assert high_low.parameter_summary["inlet2"] == 0.0
    assert low_high.error is None
    assert low_high.parameter_summary["chip_count"] == 6
    assert low_high.parameter_summary["inlet1"] == 0.0
    assert low_high.parameter_summary["inlet2"] == 1.0


def test_conflicting_dual_inlet_composite_rejects_without_partial_mutation() -> None:
    store = ConversationSessionStore()
    service = make_service(store=store)

    response = service.handle_message(
        request(
            zh(
                r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b\uff0c"
                r"\u5165\u53e31\u9ad8\u6d53\u5ea6\uff0c\u5165\u53e32\u9ad8\u6d53\u5ea6\uff0c"
                r"\u7b2c1\u4e2a\u82af\u7247\u7c7b\u578b\u662f5to4"
            )
        )
    )

    session = store.get(response.session_id)
    assert response.error is not None
    assert response.error.code == "AMBIGUOUS_INPUT"
    assert response.parameter_summary == {}
    assert "recorded" not in response.assistant_message.lower()
    assert "\u5df2\u8bb0\u5f55" not in response.assistant_message
    assert session is not None
    assert session.forward_draft.chip_count is None
    assert session.forward_draft.inlet1 is None
    assert session.forward_draft.inlet2 is None
    assert session.forward_draft.chips == {}
    assert session.active_chip_position is None


def test_low_low_and_english_high_high_inlet_conflicts_are_rejected() -> None:
    service = make_service()

    low_low = service.handle_message(
        request(
            zh(
                r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b\uff0c"
                r"\u5165\u53e31\u4f4e\u6d53\u5ea6\uff0c\u5165\u53e32\u4f4e\u6d53\u5ea6"
            )
        )
    )
    english = service.handle_message(request("use 6 chips forward, inlet 1 high, inlet 2 high", language="en"))

    assert low_low.error is not None
    assert low_low.error.code == "AMBIGUOUS_INPUT"
    assert low_low.parameter_summary == {}
    assert english.error is not None
    assert english.error.code == "AMBIGUOUS_INPUT"
    assert english.parameter_summary == {}


def test_position_shorthand_collects_chip_parameters_with_alias_fields() -> None:
    store = ConversationSessionStore()
    service = make_service(store=store)

    start = service.handle_message(
        request(zh(r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b\uff0c\u5165\u53e31\u9ad8\u6d53\u5ea6"))
    )
    response = service.handle_message(
        request(
            zh(
                r"\u4f4d\u7f6e1\uff1a5to4\uff0c"
                r"\u5de6\u5bbd.261\uff0c\u53f3\u5bbd.138\uff0c"
                r"\u5de6\u8ddd\u79bb31\uff0c\u53f3\u8ddd\u79bb25"
            ),
            start.session_id,
        )
    )

    session = store.get(start.session_id)
    assert response.error is None
    assert session is not None
    assert session.active_chip_position == 1
    assert_chip(
        session.forward_draft.chips[1].to_payload(),
        chip_type="5to4",
        left_width=0.261,
        right_width=0.138,
        left_distance=31.0,
        right_distance=25.0,
    )


def test_ordinal_chip_with_shorthand_width_and_distance_aliases() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    response = service.handle_message(
        request(
            zh(
                r"\u7b2c\u4e00\u4e2a\u82af\u7247\u7684\u82af\u7247\u7c7b\u578b5to4\uff0c"
                r"\u5de6\u5bbd.261\uff0c\u53f3\u5bbd.138\uff0c"
                r"\u5de6\u8ddd\u79bb31\uff0c\u53f3\u8ddd\u79bb25"
            ),
            session.session_id,
        )
    )

    assert response.error is None
    assert store.get(session.session_id).active_chip_position == 1
    assert_chip(
        store.get(session.session_id).forward_draft.chips[1].to_payload(),
        chip_type="5to4",
        left_width=0.261,
        right_width=0.138,
        left_distance=31.0,
        right_distance=25.0,
    )


def test_complete_six_chip_newline_only_message_reaches_confirmation() -> None:
    store = ConversationSessionStore()
    service = make_service(store=store)

    response = service.handle_message(
        request(
            zh(
                r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b\n"
                r"\u5165\u53e31\u9ad8\u6d53\u5ea6\n"
                r"\n"
                r"\u7b2c\u4e00\u4e2a\u82af\u7247\u7c7b\u578b\u662f5to4\n"
                r"\u5de6\u5bbd\u5ea6\u662f0.261\n"
                r"\u53f3\u5bbd\u5ea6\u662f0.138\n"
                r"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f31\n"
                r"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f25\n"
                r"\n"
                r"\u7b2c\u4e8c\u4e2a\u82af\u7247\u7c7b\u578b\u662f4to2\n"
                r"\u5de6\u5bbd\u5ea6\u662f0.089\n"
                r"\u53f3\u5bbd\u5ea6\u662f0.04\n"
                r"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f25\n"
                r"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f13\n"
                r"\n"
                r"\u7b2c\u4e09\u4e2a\u82af\u7247\u7c7b\u578b\u662f1to6\n"
                r"\u5de6\u5bbd\u5ea6\u662f0.212\n"
                r"\u53f3\u5bbd\u5ea6\u662f0.236\n"
                r"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f7\n"
                r"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f31\n"
                r"\n"
                r"\u7b2c\u56db\u4e2a\u82af\u7247\u7c7b\u578b\u662f2to4\n"
                r"\u5de6\u5bbd\u5ea6\u662f0.31\n"
                r"\u53f3\u5bbd\u5ea6\u662f0.163\n"
                r"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f13\n"
                r"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f25\n"
                r"\n"
                r"\u7b2c\u4e94\u4e2a\u82af\u7247\u7c7b\u578b\u662f6to3\n"
                r"\u5de6\u5bbd\u5ea6\u662f0.187\n"
                r"\u53f3\u5bbd\u5ea6\u662f0.285\n"
                r"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f37\n"
                r"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f19\n"
                r"\n"
                r"\u7b2c\u516d\u4e2a\u82af\u7247\u7c7b\u578b\u662f3to1\n"
                r"\u5de6\u5bbd\u5ea6\u662f0.05\n"
                r"\u53f3\u5bbd\u5ea6\u662f0.114\n"
                r"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f13\n"
                r"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f7"
            )
        )
    )

    session = store.get(response.session_id)
    assert response.error is None
    assert response.state == "ready_for_confirmation"
    assert response.missing_fields == []
    assert session is not None
    assert session.active_chip_position == 6
    summary = response.confirmation.summary
    assert summary["chip_count"] == 6
    assert summary["inlet1"] == 1.0
    assert summary["inlet2"] == 0.0
    chips = summary["chips"]
    expected = [
        ("5to4", 0.261, 0.138, 31.0, 25.0),
        ("4to2", 0.089, 0.04, 25.0, 13.0),
        ("1to6", 0.212, 0.236, 7.0, 31.0),
        ("2to4", 0.31, 0.163, 13.0, 25.0),
        ("6to3", 0.187, 0.285, 37.0, 19.0),
        ("3to1", 0.05, 0.114, 13.0, 7.0),
    ]
    for chip, (chip_type, left_width, right_width, left_distance, right_distance) in zip(chips, expected):
        assert_chip(
            chip,
            chip_type=chip_type,
            left_width=left_width,
            right_width=right_width,
            left_distance=left_distance,
            right_distance=right_distance,
        )


def test_complete_four_chip_position_shorthand_newline_message_reaches_confirmation() -> None:
    store = ConversationSessionStore()
    service = make_service(store=store)

    response = service.handle_message(
        request(
            zh(
                r"\u505a4\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b\n"
                r"\u5165\u53e31\u9ad8\u6d53\u5ea6\n"
                r"\n"
                r"\u4f4d\u7f6e1\uff1a5to4\n"
                r"\u5de6\u5bbd0.261\n"
                r"\u53f3\u5bbd0.138\n"
                r"\u5de6\u8ddd\u79bb31\n"
                r"\u53f3\u8ddd\u79bb25\n"
                r"\n"
                r"\u4f4d\u7f6e2\uff1a4to2\n"
                r"\u5de6\u5bbd0.089\n"
                r"\u53f3\u5bbd0.04\n"
                r"\u5de6\u8ddd\u79bb25\n"
                r"\u53f3\u8ddd\u79bb13\n"
                r"\n"
                r"\u4f4d\u7f6e3\uff1a1to6\n"
                r"\u5de6\u5bbd0.212\n"
                r"\u53f3\u5bbd0.236\n"
                r"\u5de6\u8ddd\u79bb7\n"
                r"\u53f3\u8ddd\u79bb31\n"
                r"\n"
                r"\u4f4d\u7f6e4\uff1a2to4\n"
                r"\u5de6\u5bbd0.31\n"
                r"\u53f3\u5bbd0.163\n"
                r"\u5de6\u8ddd\u79bb13\n"
                r"\u53f3\u8ddd\u79bb25"
            )
        )
    )

    session = store.get(response.session_id)
    assert response.error is None
    assert response.state == "ready_for_confirmation"
    assert response.missing_fields == []
    assert session is not None
    assert session.active_chip_position == 4
    summary = response.confirmation.summary
    assert summary["chip_count"] == 4
    assert len(summary["chips"]) == 4
    assert 5 not in session.forward_draft.chips
    assert_chip(summary["chips"][0], chip_type="5to4", left_width=0.261, right_width=0.138, left_distance=31.0, right_distance=25.0)
    assert_chip(summary["chips"][3], chip_type="2to4", left_width=0.31, right_width=0.163, left_distance=13.0, right_distance=25.0)


def test_mixed_separator_message_keeps_position_scope() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    response = service.handle_message(
        request(
            zh(
                r"\u7b2c1\u4e2a\u82af\u7247\u7c7b\u578b5to4\uff1b\n"
                r"\u5de6\u5bbd0.261\n"
                r"\u53f3\u5bbd0.138\uff1b\u5de6\u8ddd\u79bb31\n"
                r"\u53f3\u8ddd\u79bb25\u3002"
            ),
            session.session_id,
        )
    )

    assert response.error is None
    assert store.get(session.session_id).active_chip_position == 1
    assert_chip(
        store.get(session.session_id).forward_draft.chips[1].to_payload(),
        chip_type="5to4",
        left_width=0.261,
        right_width=0.138,
        left_distance=31.0,
        right_distance=25.0,
    )


def test_shorthand_field_uses_active_chip_and_no_active_remains_ambiguous() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    service.handle_message(request(zh(r"\u7b2c\u4e00\u4e2a\u82af\u7247\u7c7b\u578b\u662f5to4"), session.session_id))
    active_response = service.handle_message(request(zh(r"\u5de6\u5bbd0.261"), session.session_id))

    no_active_store = ConversationSessionStore()
    no_active_session = no_active_store.create("zh-CN")
    no_active_session.active_mode = "forward"
    no_active_session.forward_draft.set_chip_count(6)
    no_active_before = no_active_session.forward_draft.summary()
    no_active_response = make_service(store=no_active_store).handle_message(
        request(zh(r"\u5de6\u5bbd0.261"), no_active_session.session_id)
    )

    assert active_response.error is None
    assert store.get(session.session_id).forward_draft.chips[1].left_width_mm == 0.261
    assert no_active_response.error is not None
    assert no_active_response.error.code == "AMBIGUOUS_INPUT"
    assert no_active_store.get(no_active_session.session_id).forward_draft.summary() == no_active_before


def test_bare_position_number_does_not_guess_field() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    before = session.forward_draft.summary()
    service = make_service(store=store)

    position_number = service.handle_message(request(zh(r"\u4f4d\u7f6e1\uff1a.261"), session.session_id))
    ordinal_number = service.handle_message(request(zh(r"\u7b2c\u4e00\u4e2a\u82af\u72470.261"), session.session_id))

    assert position_number.error is not None
    assert position_number.error.code == "AMBIGUOUS_INPUT"
    assert ordinal_number.error is not None
    assert ordinal_number.error.code == "AMBIGUOUS_INPUT"
    assert store.get(session.session_id).forward_draft.summary() == before


def test_newline_composite_out_of_range_rejects_without_partial_mutation() -> None:
    store = ConversationSessionStore()
    service = make_service(store=store)

    response = service.handle_message(
        request(
            zh(
                r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b\n"
                r"\u5165\u53e31\u9ad8\u6d53\u5ea6\n"
                r"\u4f4d\u7f6e1\uff1a5to4\n"
                r"\u5de6\u5bbd0.261\n"
                r"\u53f3\u5bbd0.138\n"
                r"\u5de6\u8ddd\u79bb31\n"
                r"\u53f3\u8ddd\u79bb25\n"
                r"\u4f4d\u7f6e7\uff1a5to4"
            )
        )
    )

    session = store.get(response.session_id)
    assert response.error is not None
    assert response.error.code == "CHIP_INDEX_OUT_OF_RANGE"
    assert session is not None
    assert session.forward_draft.chip_count is None
    assert session.forward_draft.inlet1 is None
    assert session.forward_draft.inlet2 is None
    assert session.forward_draft.chips == {}
    assert session.active_chip_position is None


def test_contextual_omitted_chip_fields_apply_to_active_chip() -> None:
    store = ConversationSessionStore()
    service = make_service(store=store)

    first = service.handle_message(request(zh(r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b")))
    session_id = first.session_id
    service.handle_message(request(zh(r"\u5165\u53e31\u9ad8\u6d53\u5ea6"), session_id))
    service.handle_message(request(zh(r"\u7b2c\u4e00\u4e2a\u82af\u7247\u7c7b\u578b\u662f5to4"), session_id))
    service.handle_message(request(zh(r"\u5de6\u5bbd\u5ea6\u662f0.261"), session_id))
    service.handle_message(request(zh(r"\u53f3\u5bbd\u5ea6\u662f0.138"), session_id))
    service.handle_message(request(zh(r"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f31"), session_id))
    service.handle_message(request(zh(r"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f25"), session_id))
    service.handle_message(request(zh(r"\u7b2c\u4e8c\u4e2a\u82af\u7247\u7c7b\u578b\u662f4to2"), session_id))
    service.handle_message(request(zh(r"\u5de6\u5bbd\u5ea6\u662f0.089"), session_id))
    service.handle_message(request(zh(r"\u53f3\u5bbd\u5ea6\u662f0.04"), session_id))
    service.handle_message(request(zh(r"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f25"), session_id))
    response = service.handle_message(request(zh(r"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f13"), session_id))

    session = store.get(session_id)
    assert session is not None
    assert session.active_chip_position == 2
    chip1 = session.forward_draft.chips[1]
    chip2 = session.forward_draft.chips[2]
    assert chip1.chip_type == "5to4"
    assert chip1.left_width_mm == 0.261
    assert chip1.right_width_mm == 0.138
    assert chip1.left_bend_straight_distance_mm == 31.0
    assert chip1.right_bend_straight_distance_mm == 25.0
    assert chip2.chip_type == "4to2"
    assert chip2.left_width_mm == 0.089
    assert chip2.right_width_mm == 0.04
    assert chip2.left_bend_straight_distance_mm == 25.0
    assert chip2.right_bend_straight_distance_mm == 13.0
    assert response.error is None


def test_single_message_omitted_fields_follow_last_explicit_chip_position() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    response = service.handle_message(
        request(
            zh(
                r"\u7b2c1\u4e2a\u82af\u7247\u7c7b\u578b\u662f5to4\uff0c"
                r"\u5de6\u5bbd\u5ea6\u662f.261\uff0c\u53f3\u5bbd\u5ea6\u662f.138\uff0c"
                r"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f31\uff0c"
                r"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f25"
            ),
            session.session_id,
        )
    )

    chip = store.get(session.session_id).forward_draft.chips[1]
    assert response.error is None
    assert store.get(session.session_id).active_chip_position == 1
    assert chip.chip_type == "5to4"
    assert chip.left_width_mm == 0.261
    assert chip.right_width_mm == 0.138
    assert chip.left_bend_straight_distance_mm == 31.0
    assert chip.right_bend_straight_distance_mm == 25.0


def test_single_message_switches_active_chip_between_multiple_explicit_positions() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    response = service.handle_message(
        request(
            zh(
                r"\u7b2c1\u4e2a\u82af\u7247\u7c7b\u578b\u662f5to4\uff0c"
                r"\u5de6\u5bbd\u5ea6\u662f.261\uff0c"
                r"\u7b2c2\u4e2a\u82af\u7247\u7c7b\u578b\u662f4to2\uff0c"
                r"\u5de6\u5bbd\u5ea6\u662f.089"
            ),
            session.session_id,
        )
    )

    draft = store.get(session.session_id).forward_draft
    assert response.error is None
    assert store.get(session.session_id).active_chip_position == 2
    assert draft.chips[1].chip_type == "5to4"
    assert draft.chips[1].left_width_mm == 0.261
    assert draft.chips[2].chip_type == "4to2"
    assert draft.chips[2].left_width_mm == 0.089


def test_language_switch_preserves_active_chip_context() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    service = make_service(store=store)

    service.handle_message(request(zh(r"\u7b2c1\u4e2a\u82af\u7247\u5de6\u5bbd\u5ea6\u662f.261"), session.session_id))
    service.handle_message(request(zh(r"\u5207\u6362\u82f1\u6587"), session.session_id, "zh-CN"))
    response = service.handle_message(request("right width is .138", session.session_id, "en"))

    draft = store.get(session.session_id).forward_draft
    assert response.error is None
    assert store.get(session.session_id).language == "en"
    assert store.get(session.session_id).active_chip_position == 1
    assert draft.chips[1].left_width_mm == 0.261
    assert draft.chips[1].right_width_mm == 0.138


def test_reset_mode_switch_and_successful_shrink_clear_active_chip_context() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    session.active_chip_position = 6
    service = make_service(store=store)

    shrink = service.handle_message(request(zh(r"\u8bbe\u7f6e4\u4e2a\u82af\u7247"), session.session_id))
    assert shrink.error is None
    assert store.get(session.session_id).active_chip_position is None

    service.handle_message(request(zh(r"\u7b2c1\u4e2a\u82af\u7247\u5de6\u5bbd\u5ea6\u662f.1"), session.session_id))
    reverse = service.handle_message(request(zh(r"\u5f00\u59cb\u53cd\u5411\u9884\u6d4b"), session.session_id))
    assert reverse.error is None
    assert store.get(session.session_id).active_mode == "reverse"
    assert store.get(session.session_id).active_chip_position is None

    store.get(session.session_id).active_chip_position = 1
    reset = service.handle_message(request("reset", session.session_id, "en"))
    assert reset.error is None
    assert store.get(session.session_id).active_chip_position is None


def test_invalid_contextual_composite_does_not_partially_mutate_draft_or_active_chip() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(4)
    session.active_chip_position = 2
    before = session.forward_draft.summary()
    service = make_service(store=store)

    response = service.handle_message(
        request(
            zh(
                r"\u7b2c1\u4e2a\u82af\u7247\u5de6\u5bbd\u5ea6\u662f.1\uff0c"
                r"\u7b2c5\u4e2a\u82af\u7247\u53f3\u5bbd\u5ea6\u662f.138"
            ),
            session.session_id,
        )
    )

    session = store.get(session.session_id)
    assert response.error is not None
    assert response.error.code == "CHIP_INDEX_OUT_OF_RANGE"
    assert session.forward_draft.summary() == before
    assert session.active_chip_position == 2


def test_out_of_range_or_invalid_width_context_update_does_not_change_active_chip() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(4)
    session.active_chip_position = 2
    before = session.forward_draft.summary()
    service = make_service(store=store)

    out_of_range = service.handle_message(
        request(zh(r"\u7b2c5\u4e2a\u82af\u7247\u53f3\u5bbd\u5ea6\u662f.138"), session.session_id)
    )
    invalid_width = service.handle_message(request(zh(r"\u53f3\u5bbd\u5ea6\u662f0.311"), session.session_id))

    session = store.get(session.session_id)
    assert out_of_range.error is not None
    assert out_of_range.error.code == "CHIP_INDEX_OUT_OF_RANGE"
    assert invalid_width.error is not None
    assert invalid_width.error.code == "VALIDATION_ERROR"
    assert session.forward_draft.summary() == before
    assert session.active_chip_position == 2


def test_complete_six_chip_chinese_ordinal_forward_draft_reaches_confirmation() -> None:
    service = make_service(adapter=FakeForwardAdapter())
    session_id = None
    messages = [
        zh(r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b"),
        zh(r"\u5165\u53e31\u9ad8\u6d53\u5ea6"),
    ]
    chip_rows = [
        (1, "5to4", 0.261, 0.138, 31, 25),
        (2, "4to2", 0.089, 0.04, 25, 13),
        (3, "1to6", 0.212, 0.236, 7, 31),
        (4, "2to4", 0.31, 0.163, 13, 25),
        (5, "6to3", 0.187, 0.285, 37, 19),
        (6, "3to1", 0.05, 0.114, 13, 7),
    ]
    for position, chip_type, left_width, right_width, left_distance, right_distance in chip_rows:
        messages.extend(
            [
                zh(rf"\u7b2c{position}\u4e2a\u82af\u7247\u7c7b\u578b\u662f{chip_type}"),
                zh(rf"\u7b2c{position}\u4e2a\u82af\u7247\u5de6\u5bbd\u5ea6\u662f{left_width}"),
                zh(rf"\u7b2c{position}\u4e2a\u82af\u7247\u53f3\u5bbd\u5ea6\u662f{right_width}"),
                zh(rf"\u7b2c{position}\u4e2a\u82af\u7247\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f{left_distance}"),
                zh(rf"\u7b2c{position}\u4e2a\u82af\u7247\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f{right_distance}"),
            ]
        )

    response = None
    for message in messages:
        response = service.handle_message(request(message, session_id))
        session_id = response.session_id
        assert response.forward_prediction is None

    assert response is not None
    assert response.state == "ready_for_confirmation"
    assert response.confirmation is not None
    assert response.missing_fields == []
    summary = response.confirmation.summary
    assert summary["chip_count"] == 6
    chips = summary["chips"]
    assert chips[0]["chip_type"] == "5to4"
    assert chips[0]["left_width_mm"] == 0.261
    assert chips[0]["right_width_mm"] == 0.138
    assert chips[0]["left_bend_straight_distance_mm"] == 31.0
    assert chips[0]["right_bend_straight_distance_mm"] == 25.0
    assert chips[5]["chip_type"] == "3to1"


def test_complete_six_chip_contextual_forward_draft_reaches_confirmation_without_model_call() -> None:
    adapter = FakeForwardAdapter()
    service = make_service(adapter=adapter)
    session_id = None
    chip_rows = [
        (1, "5to4", 0.261, 0.138, 31, 25),
        (2, "4to2", 0.089, 0.04, 25, 13),
        (3, "1to6", 0.212, 0.236, 7, 31),
        (4, "2to4", 0.31, 0.163, 13, 25),
        (5, "6to3", 0.187, 0.285, 37, 19),
        (6, "3to1", 0.05, 0.114, 13, 7),
    ]
    messages = [
        zh(r"\u505a6\u4e2a\u82af\u7247\u6b63\u5411\u9884\u6d4b"),
        zh(r"\u5165\u53e31\u9ad8\u6d53\u5ea6"),
    ]
    for position, chip_type, left_width, right_width, left_distance, right_distance in chip_rows:
        messages.extend(
            [
                zh(rf"\u7b2c{position}\u4e2a\u82af\u7247\u7c7b\u578b\u662f{chip_type}"),
                zh(rf"\u5de6\u5bbd\u5ea6\u662f{left_width}"),
                zh(rf"\u53f3\u5bbd\u5ea6\u662f{right_width}"),
                zh(rf"\u5de6\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f{left_distance}"),
                zh(rf"\u53f3\u5f2f\u66f2\u76f4\u9053\u8ddd\u79bb\u662f{right_distance}"),
            ]
        )

    response = None
    for message in messages:
        response = service.handle_message(request(message, session_id))
        session_id = response.session_id
        assert response.forward_prediction is None
        assert adapter.calls == 0

    assert response is not None
    assert response.state == "ready_for_confirmation"
    assert response.confirmation is not None
    assert response.missing_fields == []
    assert response.confirmation.summary["chip_count"] == 6
    chips = response.confirmation.summary["chips"]
    assert chips[0]["chip_type"] == "5to4"
    assert chips[0]["left_width_mm"] == 0.261
    assert chips[0]["right_width_mm"] == 0.138
    assert chips[5]["chip_type"] == "3to1"
    assert chips[5]["right_bend_straight_distance_mm"] == 7.0


def test_shrinking_chip_count_with_tail_parameters_is_rejected_without_deletion() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(6)
    session.forward_draft.chips[5].left_width_mm = 0.11
    session.forward_draft.chips[6].right_width_mm = 0.22
    service = make_service(store=store)

    response = service.handle_message(request("set 4 chips", session.session_id, "en"))

    draft = store.get(session.session_id).forward_draft
    assert response.error is not None
    assert response.error.code == "CHIP_COUNT_CHANGE_REQUIRES_RESET"
    assert draft.chip_count == 6
    assert draft.chips[5].left_width_mm == 0.11
    assert draft.chips[6].right_width_mm == 0.22


def test_increasing_chip_count_preserves_existing_parameters() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    session.active_mode = "forward"
    session.forward_draft.set_chip_count(4)
    session.forward_draft.chips[1].left_width_mm = 0.11
    service = make_service(store=store)

    response = service.handle_message(request("set 6 chips", session.session_id, "en"))

    draft = store.get(session.session_id).forward_draft
    assert response.error is None
    assert draft.chip_count == 6
    assert draft.chips[1].left_width_mm == 0.11
    assert 6 in draft.chips


def test_reverse_collecting_cancel_only_clears_draft() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    session.active_mode = "reverse"
    session.state = "collecting"
    session.reverse_draft.target_concentrations = [0.1, 0.2]
    manager = FakeReverseTaskManager()
    service = make_service(store=store, reverse_manager=manager)

    response = service.handle_message(request("cancel", session.session_id, "en"))

    assert response.state == "idle"
    assert manager.cancel_calls == 0
    assert store.get(session.session_id).reverse_draft.target_concentrations == []


def test_reverse_running_cancel_calls_task_manager_once() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    session.active_mode = "reverse"
    session.state = "running"
    session.last_reverse_task_id = "task-1"
    manager = FakeReverseTaskManager()
    service = make_service(store=store, reverse_manager=manager)

    response = service.handle_message(request("cancel", session.session_id, "en"))

    assert response.state == "completed"
    assert manager.cancel_calls == 1
    assert response.reverse_task is not None
    assert response.reverse_task.status == "cancelled"
    assert "cancelled" in response.assistant_message.lower()


def test_reverse_cancel_does_not_claim_cancelled_for_terminal_status() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    session.active_mode = "reverse"
    session.state = "running"
    session.last_reverse_task_id = "task-1"
    manager = FakeReverseTaskManager()
    manager.cancel_status = ReverseTaskCreatedResponse(task_id="task-1", status="completed")
    service = make_service(store=store, reverse_manager=manager)

    response = service.handle_message(request("cancel", session.session_id, "en"))

    assert manager.cancel_calls == 1
    assert response.reverse_task is not None
    assert response.reverse_task.status == "completed"
    assert response.assistant_message != "The reverse prediction task has been cancelled."


def test_repeated_forward_confirm_does_not_repeat_adapter_call() -> None:
    store = ConversationSessionStore()
    session_id = fill_complete_forward_session(store)
    adapter = FakeForwardAdapter()
    service = make_service(store=store, adapter=adapter)

    first = service.handle_message(request("run", session_id))
    second = service.handle_message(request("run", session_id))

    assert first.state == "completed"
    assert second.forward_prediction is None
    assert adapter.calls == 1


def test_forward_schema_validation_failure_does_not_call_adapter() -> None:
    store = ConversationSessionStore()
    session_id = fill_complete_forward_session(store)
    session = store.get(session_id)
    assert session is not None
    session.forward_draft.chips[1].left_width_mm = 0.5
    adapter = FakeForwardAdapter()
    service = make_service(store=store, adapter=adapter)

    response = service.handle_message(request("run", session_id))

    assert response.error is not None
    assert response.error.code == "VALIDATION_ERROR"
    assert adapter.calls == 0
