from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.chat.schemas import ChatLanguage, ChatMode, ChatState
from app.schemas.forward import ForwardPredictionRequest

DEFAULT_SAMPLE_NAME = "chat-forward"


@dataclass
class ChipDraft:
    position: int
    chip_type: str | None = None
    left_width_mm: float | None = None
    right_width_mm: float | None = None
    left_bend_straight_distance_mm: float | None = None
    right_bend_straight_distance_mm: float | None = None

    def has_any_parameter(self) -> bool:
        return any(
            getattr(self, field_name) is not None
            for field_name in (
                "chip_type",
                "left_width_mm",
                "right_width_mm",
                "left_bend_straight_distance_mm",
                "right_bend_straight_distance_mm",
            )
        )

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        for field_name in (
            "chip_type",
            "left_width_mm",
            "right_width_mm",
            "left_bend_straight_distance_mm",
            "right_bend_straight_distance_mm",
        ):
            if getattr(self, field_name) is None:
                missing.append(f"chips.{self.position}.{field_name}")
        return missing

    def to_payload(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "chip_type": self.chip_type,
            "left_width_mm": self.left_width_mm,
            "right_width_mm": self.right_width_mm,
            "left_bend_straight_distance_mm": self.left_bend_straight_distance_mm,
            "right_bend_straight_distance_mm": self.right_bend_straight_distance_mm,
        }


@dataclass
class ForwardDraft:
    sample_name: str = DEFAULT_SAMPLE_NAME
    chip_count: int | None = None
    inlet1: float | None = None
    inlet2: float | None = None
    chips: dict[int, ChipDraft] = field(default_factory=dict)

    def can_change_chip_count(self, chip_count: int) -> bool:
        if self.chip_count is None or chip_count >= self.chip_count:
            return True
        return not any(
            chip.position > chip_count and chip.has_any_parameter()
            for chip in self.chips.values()
        )

    def set_chip_count(self, chip_count: int) -> None:
        self.chip_count = chip_count
        self.chips = {
            position: self.chips.get(position, ChipDraft(position=position))
            for position in range(1, chip_count + 1)
        }

    def ensure_chip(self, position: int) -> ChipDraft:
        chip = self.chips.get(position)
        if chip is None:
            chip = ChipDraft(position=position)
            self.chips[position] = chip
        return chip

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if self.sample_name is None or not self.sample_name.strip():
            missing.append("sample_name")
        if self.chip_count is None:
            missing.append("chip_count")
            return missing
        if self.inlet1 is None or self.inlet2 is None:
            missing.append("inlet")
        for position in range(1, self.chip_count + 1):
            missing.extend(self.ensure_chip(position).missing_fields())
        return missing

    def is_complete(self) -> bool:
        return not self.missing_fields()

    def summary(self) -> dict[str, Any]:
        return {
            "sample_name": self.sample_name,
            "chip_count": self.chip_count,
            "inlet1": self.inlet1,
            "inlet2": self.inlet2,
            "chips": [self.chips[position].to_payload() for position in sorted(self.chips)],
        }

    def to_request(self) -> ForwardPredictionRequest:
        if self.chip_count is None:
            raise ValueError("forward draft is missing chip_count")
        return ForwardPredictionRequest(
            sample_name=self.sample_name,
            chip_count=self.chip_count,
            inlet1=self.inlet1,
            inlet2=self.inlet2,
            chips=[self.chips[position].to_payload() for position in range(1, self.chip_count + 1)],
        )


@dataclass
class ReverseChatRequest:
    target_concentrations: list[float]


@dataclass
class ReverseDraft:
    inlet1: float | None = None
    inlet2: float | None = None
    target_concentrations: list[float] = field(default_factory=list)

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if len(self.target_concentrations) != 6:
            missing.append("target_concentrations")
        return missing

    def is_complete(self) -> bool:
        return not self.missing_fields()

    def summary(self) -> dict[str, Any]:
        targets = list(self.target_concentrations)
        return {
            "target_position_count": 6,
            "target_concentrations": targets,
            "target_positions": [
                {"position": index + 1, "target_concentration": concentration}
                for index, concentration in enumerate(targets)
            ],
        }

    def to_request(self) -> ReverseChatRequest:
        return ReverseChatRequest(target_concentrations=list(self.target_concentrations))


@dataclass
class ConversationSession:
    session_id: str
    language: ChatLanguage
    active_mode: ChatMode = "idle"
    state: ChatState = "idle"
    forward_draft: ForwardDraft = field(default_factory=ForwardDraft)
    reverse_draft: ReverseDraft = field(default_factory=ReverseDraft)
    last_forward_result: Any = None
    last_reverse_task_id: str | None = None
    pending_confirmation: ChatMode | None = None
    active_chip_position: int | None = None

    def reset(self) -> None:
        self.active_mode = "idle"
        self.state = "idle"
        self.forward_draft = ForwardDraft()
        self.reverse_draft = ReverseDraft()
        self.last_forward_result = None
        self.last_reverse_task_id = None
        self.pending_confirmation = None
        self.active_chip_position = None

    def cancel_current_draft(self) -> None:
        if self.active_mode == "forward":
            self.forward_draft = ForwardDraft()
            self.active_chip_position = None
        elif self.active_mode == "reverse":
            self.reverse_draft = ReverseDraft()
        self.active_mode = "idle"
        self.state = "idle"
        self.pending_confirmation = None


class ConversationSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def create(self, language: ChatLanguage = "zh-CN") -> ConversationSession:
        session = ConversationSession(session_id=uuid.uuid4().hex, language=language)
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> ConversationSession | None:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: str | None, language: ChatLanguage) -> ConversationSession:
        session = self.get(session_id) if session_id else None
        if session is None:
            return self.create(language)
        session.language = language
        return session

    def reset(self, session_id: str) -> ConversationSession | None:
        session = self.get(session_id)
        if session is not None:
            session.reset()
        return session
