from __future__ import annotations

from app.chat.schemas import ChatMessageRequest
from app.chat.service import ChatService
from app.chat.session import ChipDraft, ConversationSessionStore
from app.core.errors import ModelErrorCode, ModelRuntimeError
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


def test_unknown_chip_count_rejects_p_values_without_saving_draft() -> None:
    store = ConversationSessionStore()
    session = store.create("en")
    service = make_service(store=store)

    response = service.handle_message(request("P1 0.12", session.session_id, "en"))

    assert response.error is not None
    assert response.error.code == "CHIP_COUNT_REQUIRED"
    assert store.get(session.session_id).forward_draft.chips == {}


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
