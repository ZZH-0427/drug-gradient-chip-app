from __future__ import annotations

from app.chat.session import ConversationSessionStore


def test_session_store_creates_and_reuses_session() -> None:
    store = ConversationSessionStore()
    first = store.get_or_create(None, "zh-CN")
    second = store.get_or_create(first.session_id, "zh-CN")

    assert first.session_id
    assert second is first


def test_session_reset_clears_drafts() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.active_mode = "forward"
    session.state = "collecting"
    session.forward_draft.set_chip_count(6)
    session.forward_draft.inlet1 = 1.0
    session.forward_draft.inlet2 = 0.0

    store.reset(session.session_id)

    assert session.active_mode == "idle"
    assert session.state == "idle"
    assert session.forward_draft.chip_count is None


def test_session_language_is_retained_and_updated() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")

    reused = store.get_or_create(session.session_id, "en")

    assert reused is session
    assert session.language == "en"


def test_forward_and_reverse_drafts_are_isolated() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")

    session.forward_draft.set_chip_count(6)
    session.reverse_draft.target_concentrations = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]

    assert session.forward_draft.chip_count == 6
    assert session.reverse_draft.target_concentrations == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


def test_cancel_current_draft_clears_only_active_mode() -> None:
    store = ConversationSessionStore()
    session = store.create("zh-CN")
    session.forward_draft.set_chip_count(6)
    session.reverse_draft.target_concentrations = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    session.active_mode = "forward"

    session.cancel_current_draft()

    assert session.active_mode == "idle"
    assert session.forward_draft.chip_count is None
    assert session.reverse_draft.target_concentrations == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
