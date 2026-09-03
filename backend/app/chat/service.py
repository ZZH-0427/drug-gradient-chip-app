from __future__ import annotations

from typing import Any, Protocol

from pydantic import ValidationError

from app.chat.formatter import message, summarize_missing
from app.chat.parser import DeterministicChatParser, ParsedMessage
from app.chat.schemas import ChatConfirmation, ChatError, ChatMessageRequest, ChatMessageResponse
from app.chat.session import ConversationSession, ConversationSessionStore
from app.core.errors import ModelRuntimeError
from app.core.model_state import ForwardAdapterProtocol
from app.schemas.forward import FORWARD_WIDTH_MAX_MM, FORWARD_WIDTH_MIN_MM
from app.schemas.reverse import ReverseTaskCreatedResponse


class ReverseTaskManagerProtocol(Protocol):
    def create(self, request: object) -> object:
        ...

    def cancel(self, task_id: str) -> object | None:
        ...


class ChatService:
    def __init__(
        self,
        *,
        sessions: ConversationSessionStore,
        parser: DeterministicChatParser | None = None,
        forward_adapter: ForwardAdapterProtocol | None = None,
        reverse_manager: ReverseTaskManagerProtocol | None = None,
    ) -> None:
        self.sessions = sessions
        self.parser = parser or DeterministicChatParser()
        self.forward_adapter = forward_adapter
        self.reverse_manager = reverse_manager

    def handle_message(self, request: ChatMessageRequest) -> ChatMessageResponse:
        session = self.sessions.get_or_create(request.session_id, request.language)
        parsed = self.parser.parse(request.message)
        if parsed.intent == "switch_language":
            session.language = parsed.fields["language"]
        else:
            session.language = request.language

        if parsed.ambiguity:
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "ambiguous"),
                error=ChatError(code="AMBIGUOUS_INPUT", message="Ambiguous input."),
            )

        try:
            return self._handle_parsed(session, parsed)
        except ValidationError:
            session.state = "error"
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "validation_error"),
                error=ChatError(code="VALIDATION_ERROR", message="Request validation failed."),
            )
        except ModelRuntimeError:
            session.state = "error"
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "runtime_error"),
                error=ChatError(code="MODEL_RUNTIME_ERROR", message="Model request failed."),
            )
        except Exception:
            session.state = "error"
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "runtime_error"),
                error=ChatError(code="CHAT_SERVICE_ERROR", message="Chat service failed."),
            )

    def _handle_parsed(self, session: ConversationSession, parsed: ParsedMessage) -> ChatMessageResponse:
        if parsed.intent == "help":
            return self._response(session, parsed, assistant_message=message(session.language, "help"))
        if parsed.intent == "reset":
            session.reset()
            session.language = parsed.fields.get("language", session.language)
            return self._response(session, parsed, assistant_message=message(session.language, "reset"))
        if parsed.intent == "cancel":
            return self._cancel(session, parsed)
        if parsed.intent == "switch_language":
            return self._response(session, parsed, assistant_message=message(session.language, "language"))
        if parsed.intent == "start_forward":
            return self._handle_forward_turn(session, parsed)
        if parsed.intent == "start_reverse":
            session.active_chip_position = None
            session.active_mode = "reverse"
            if "inlet1" in parsed.fields and "inlet2" in parsed.fields:
                session.reverse_draft.inlet1 = float(parsed.fields["inlet1"])
                session.reverse_draft.inlet2 = float(parsed.fields["inlet2"])
            return self._after_reverse_mutation(session, parsed)
        if parsed.intent == "set_chip_count":
            return self._handle_forward_turn(session, parsed)
        if parsed.intent == "set_inlet":
            if parsed.fields.get("chip_parameter_updates") or "chip_count" in parsed.fields:
                return self._handle_forward_turn(session, parsed)
            self._apply_inlet(session, parsed)
            return self._after_active_mutation(session, parsed)
        if parsed.intent == "set_chip_parameter":
            return self._handle_forward_turn(session, parsed)
        if parsed.intent == "set_target_concentration":
            session.active_chip_position = None
            session.active_mode = "reverse"
            if "inlet1" in parsed.fields and "inlet2" in parsed.fields:
                session.reverse_draft.inlet1 = float(parsed.fields["inlet1"])
                session.reverse_draft.inlet2 = float(parsed.fields["inlet2"])
            session.reverse_draft.target_concentrations = list(parsed.fields["target_concentrations"])
            return self._after_reverse_mutation(session, parsed)
        if parsed.intent == "show_parameters":
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "collecting"),
                missing_fields=self._active_missing_fields(session),
            )
        if parsed.intent in {"confirm", "run_prediction"}:
            return self._run_if_ready(session, parsed)
        return self._response(
            session,
            parsed,
            assistant_message=message(session.language, "unsupported"),
            error=ChatError(code="UNSUPPORTED_EXPRESSION", message="Unsupported expression."),
        )

    def _cancel(self, session: ConversationSession, parsed: ParsedMessage) -> ChatMessageResponse:
        if (
            session.active_mode == "reverse"
            and session.state == "running"
            and session.last_reverse_task_id
            and self.reverse_manager is not None
        ):
            try:
                status = self.reverse_manager.cancel(session.last_reverse_task_id)
            except RuntimeError:
                session.pending_confirmation = None
                session.state = "completed"
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "reverse_not_cancelled"),
                    error=ChatError(code="REVERSE_TASK_NOT_CANCELLABLE", message="Reverse task is not cancellable."),
                )
            if status is None:
                session.pending_confirmation = None
                session.state = "error"
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "runtime_error"),
                    error=ChatError(code="REVERSE_TASK_NOT_FOUND", message="Reverse task was not found."),
                )
            reverse_task = ReverseTaskCreatedResponse(task_id=status.task_id, status=status.status)
            session.pending_confirmation = None
            session.state = "completed" if status.status in {"completed", "failed", "cancelled"} else "running"
            return self._response(
                session,
                parsed,
                assistant_message=message(
                    session.language,
                    "reverse_cancelled" if status.status == "cancelled" else "reverse_not_cancelled",
                ),
                reverse_task=reverse_task,
            )
        session.cancel_current_draft()
        return self._response(session, parsed, assistant_message=message(session.language, "cancel"))

    def _set_forward_chip_count(
        self,
        session: ConversationSession,
        parsed: ParsedMessage,
        chip_count: int,
    ) -> ChatMessageResponse | None:
        if not session.forward_draft.can_change_chip_count(chip_count):
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "chip_count_shrink_rejected"),
                error=ChatError(
                    code="CHIP_COUNT_CHANGE_REQUIRES_RESET",
                    message="Reducing chip count would delete existing tail chip parameters.",
                ),
            )
        session.forward_draft.set_chip_count(chip_count)
        if session.active_chip_position is not None and session.active_chip_position > chip_count:
            session.active_chip_position = None
        return None

    def _handle_forward_turn(self, session: ConversationSession, parsed: ParsedMessage) -> ChatMessageResponse:
        validation = self._validate_forward_turn(session, parsed)
        if validation is not None:
            return validation

        if session.active_mode != "forward":
            session.active_chip_position = None
        session.active_mode = "forward"
        if "chip_count" in parsed.fields:
            response = self._set_forward_chip_count(session, parsed, int(parsed.fields["chip_count"]))
            if response is not None:
                return response
        if "inlet1" in parsed.fields and "inlet2" in parsed.fields:
            session.forward_draft.inlet1 = float(parsed.fields["inlet1"])
            session.forward_draft.inlet2 = float(parsed.fields["inlet2"])
        for point, value in parsed.fields.get("p_values", {}).items():
            position = (int(point) + 1) // 2
            chip = session.forward_draft.ensure_chip(position)
            if int(point) % 2 == 1:
                chip.left_width_mm = float(value)
            else:
                chip.right_width_mm = float(value)
        for update in self._resolved_chip_updates(session, parsed):
            position = int(update["chip_position"])
            chip = session.forward_draft.ensure_chip(position)
            if "chip_field" in update:
                setattr(chip, str(update["chip_field"]), float(update["value"]))
            if "chip_type" in update:
                chip.chip_type = str(update["chip_type"])
            if "chip_updates" in update:
                for field_name, value in update["chip_updates"].items():
                    setattr(chip, str(field_name), float(value))
            if update.get("explicit_position"):
                session.active_chip_position = position
        return self._after_forward_mutation(session, parsed)

    def _validate_forward_turn(
        self,
        session: ConversationSession,
        parsed: ParsedMessage,
    ) -> ChatMessageResponse | None:
        fields = parsed.fields
        effective_chip_count = int(fields["chip_count"]) if "chip_count" in fields else session.forward_draft.chip_count
        if "chip_count" in fields and not session.forward_draft.can_change_chip_count(int(fields["chip_count"])):
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "chip_count_shrink_rejected"),
                error=ChatError(
                    code="CHIP_COUNT_CHANGE_REQUIRES_RESET",
                    message="Reducing chip count would delete existing tail chip parameters.",
                ),
            )
        if "p_values" in fields:
            if effective_chip_count is None:
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "chip_count_required"),
                    error=ChatError(code="CHIP_COUNT_REQUIRED", message="Chip count is required before P values."),
                )
            max_point = effective_chip_count * 2
            if any(int(point) > max_point for point in fields["p_values"]):
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "p_index_out_of_range"),
                    error=ChatError(code="P_INDEX_OUT_OF_RANGE", message="P point exceeds chip_count range."),
                )
        for update in self._resolved_chip_updates(session, parsed):
            position = update.get("chip_position")
            if position is None:
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "ambiguous"),
                    error=ChatError(code="AMBIGUOUS_INPUT", message="Ambiguous input."),
                )
            if effective_chip_count is not None and int(position) > effective_chip_count:
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "chip_index_out_of_range"),
                    error=ChatError(code="CHIP_INDEX_OUT_OF_RANGE", message="Chip position exceeds chip_count range."),
                )
            if "chip_field" in update:
                field_name = str(update["chip_field"])
                value = float(update["value"])
                if field_name in {"left_width_mm", "right_width_mm"} and (
                    value < FORWARD_WIDTH_MIN_MM or value > FORWARD_WIDTH_MAX_MM
                ):
                    return self._response(
                        session,
                        parsed,
                        assistant_message=message(session.language, "validation_error"),
                        error=ChatError(code="VALIDATION_ERROR", message="Request validation failed."),
                    )
            if "chip_updates" in update:
                for field_name, value in update["chip_updates"].items():
                    if field_name in {"left_width_mm", "right_width_mm"} and (
                        float(value) < FORWARD_WIDTH_MIN_MM or float(value) > FORWARD_WIDTH_MAX_MM
                    ):
                        return self._response(
                            session,
                            parsed,
                            assistant_message=message(session.language, "validation_error"),
                            error=ChatError(code="VALIDATION_ERROR", message="Request validation failed."),
                        )
        return None

    def _resolved_chip_updates(
        self,
        session: ConversationSession,
        parsed: ParsedMessage,
    ) -> list[dict[str, Any]]:
        raw_updates = parsed.fields.get("chip_parameter_updates")
        updates: list[dict[str, Any]]
        if isinstance(raw_updates, list):
            updates = [dict(update) for update in raw_updates if isinstance(update, dict)]
        elif any(key in parsed.fields for key in ("chip_position", "chip_field", "chip_type", "chip_updates")):
            updates = [dict(parsed.fields)]
        else:
            return []
        for update in updates:
            if update.get("chip_position") is not None and "explicit_position" not in update:
                update["explicit_position"] = True
            if update.get("chip_position") is None:
                update["chip_position"] = session.active_chip_position
                update["explicit_position"] = False
        return updates

    def _validate_forward_fields(
        self,
        session: ConversationSession,
        parsed: ParsedMessage,
    ) -> ChatMessageResponse | None:
        fields = parsed.fields
        chip_count = session.forward_draft.chip_count
        if "p_values" in fields:
            if chip_count is None:
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "chip_count_required"),
                    error=ChatError(code="CHIP_COUNT_REQUIRED", message="Chip count is required before P values."),
                )
            max_point = chip_count * 2
            if any(int(point) > max_point for point in fields["p_values"]):
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "p_index_out_of_range"),
                    error=ChatError(code="P_INDEX_OUT_OF_RANGE", message="P point exceeds chip_count range."),
                )
        if "chip_position" in fields and chip_count is not None and int(fields["chip_position"]) > chip_count:
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "chip_index_out_of_range"),
                error=ChatError(code="CHIP_INDEX_OUT_OF_RANGE", message="Chip position exceeds chip_count range."),
            )
        return None

    def _apply_inlet(self, session: ConversationSession, parsed: ParsedMessage) -> None:
        if session.active_mode == "reverse":
            session.reverse_draft.inlet1 = float(parsed.fields["inlet1"])
            session.reverse_draft.inlet2 = float(parsed.fields["inlet2"])
            return
        session.active_mode = "forward"
        session.forward_draft.inlet1 = float(parsed.fields["inlet1"])
        session.forward_draft.inlet2 = float(parsed.fields["inlet2"])

    def _apply_forward_fields(self, session: ConversationSession, fields: dict[str, Any]) -> None:
        if "p_values" in fields:
            for point, value in fields["p_values"].items():
                position = (int(point) + 1) // 2
                chip = session.forward_draft.ensure_chip(position)
                if int(point) % 2 == 1:
                    chip.left_width_mm = float(value)
                else:
                    chip.right_width_mm = float(value)
        if {"chip_position", "chip_field", "value"}.issubset(fields):
            chip = session.forward_draft.ensure_chip(int(fields["chip_position"]))
            setattr(chip, str(fields["chip_field"]), float(fields["value"]))
        if {"chip_position", "chip_type"}.issubset(fields):
            chip = session.forward_draft.ensure_chip(int(fields["chip_position"]))
            chip.chip_type = str(fields["chip_type"])
        if {"chip_position", "chip_updates"}.issubset(fields):
            chip = session.forward_draft.ensure_chip(int(fields["chip_position"]))
            for field_name, value in fields["chip_updates"].items():
                setattr(chip, str(field_name), float(value))

    def _after_active_mutation(self, session: ConversationSession, parsed: ParsedMessage) -> ChatMessageResponse:
        if session.active_mode == "reverse":
            return self._after_reverse_mutation(session, parsed)
        return self._after_forward_mutation(session, parsed)

    def _after_forward_mutation(self, session: ConversationSession, parsed: ParsedMessage) -> ChatMessageResponse:
        missing = session.forward_draft.missing_fields()
        if missing:
            session.state = "collecting"
            session.pending_confirmation = None
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "collecting"),
                missing_fields=missing,
            )
        session.state = "ready_for_confirmation"
        session.pending_confirmation = "forward"
        return self._response(
            session,
            parsed,
            assistant_message=message(session.language, "ready"),
            confirmation=ChatConfirmation(mode="forward", summary=session.forward_draft.summary()),
        )

    def _after_reverse_mutation(self, session: ConversationSession, parsed: ParsedMessage) -> ChatMessageResponse:
        missing = session.reverse_draft.missing_fields()
        if missing:
            session.state = "collecting"
            session.pending_confirmation = None
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "collecting"),
                missing_fields=missing,
            )
        session.state = "ready_for_confirmation"
        session.pending_confirmation = "reverse"
        return self._response(
            session,
            parsed,
            assistant_message=message(session.language, "ready"),
            confirmation=ChatConfirmation(mode="reverse", summary=session.reverse_draft.summary()),
        )

    def _run_if_ready(self, session: ConversationSession, parsed: ParsedMessage) -> ChatMessageResponse:
        if session.pending_confirmation == "forward":
            missing = session.forward_draft.missing_fields()
            if missing:
                session.state = "collecting"
                return self._response(session, parsed, assistant_message=message(session.language, "collecting"), missing_fields=missing)
            if self.forward_adapter is None:
                session.state = "error"
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "runtime_error"),
                    error=ChatError(code="MODEL_NOT_READY", message="Forward model is not ready."),
                )
            prediction = self.forward_adapter.predict(session.forward_draft.to_request())
            session.last_forward_result = prediction
            session.state = "completed"
            session.pending_confirmation = None
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "forward_completed"),
                forward_prediction=prediction,
            )
        if session.pending_confirmation == "reverse":
            missing = session.reverse_draft.missing_fields()
            if missing:
                session.state = "collecting"
                return self._response(session, parsed, assistant_message=message(session.language, "collecting"), missing_fields=missing)
            if self.reverse_manager is None:
                session.state = "error"
                return self._response(
                    session,
                    parsed,
                    assistant_message=message(session.language, "runtime_error"),
                    error=ChatError(code="REVERSE_MODEL_UNAVAILABLE", message="Reverse model is not ready."),
                )
            created = self.reverse_manager.create(session.reverse_draft.to_request())
            reverse_task = ReverseTaskCreatedResponse(task_id=created.task_id, status=created.status)
            session.last_reverse_task_id = reverse_task.task_id
            session.state = "running"
            session.pending_confirmation = None
            return self._response(
                session,
                parsed,
                assistant_message=message(session.language, "reverse_created"),
                reverse_task=reverse_task,
            )
        missing = self._active_missing_fields(session)
        session.state = "collecting" if missing else session.state
        return self._response(
            session,
            parsed,
            assistant_message=message(session.language, "collecting" if missing else "unsupported"),
            missing_fields=missing,
        )

    def _active_missing_fields(self, session: ConversationSession) -> list[str]:
        if session.active_mode == "forward":
            return session.forward_draft.missing_fields()
        if session.active_mode == "reverse":
            return session.reverse_draft.missing_fields()
        return []

    def _response(
        self,
        session: ConversationSession,
        parsed: ParsedMessage,
        *,
        assistant_message: str,
        missing_fields: list[str] | None = None,
        confirmation: ChatConfirmation | None = None,
        forward_prediction: Any = None,
        reverse_task: ReverseTaskCreatedResponse | None = None,
        error: ChatError | None = None,
    ) -> ChatMessageResponse:
        active_missing = missing_fields if missing_fields is not None else self._active_missing_fields(session)
        summary: dict[str, Any]
        if session.active_mode == "forward":
            summary = session.forward_draft.summary()
        elif session.active_mode == "reverse":
            summary = session.reverse_draft.summary()
        else:
            summary = {}
        if active_missing:
            summary = {**summary, **summarize_missing(active_missing)}
        return ChatMessageResponse(
            session_id=session.session_id,
            state=session.state,
            intent=parsed.intent,
            assistant_message=assistant_message,
            missing_fields=active_missing,
            parameter_summary=summary,
            confirmation=confirmation,
            forward_prediction=forward_prediction,
            reverse_task=reverse_task,
            error=error,
        )
