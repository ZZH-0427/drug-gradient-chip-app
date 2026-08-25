from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes.chat import get_chat_session_store
from app.chat.session import ConversationSessionStore
from app.main import create_app


def client_with_store(store: ConversationSessionStore) -> TestClient:
    app = create_app(load_model=False)
    app.dependency_overrides[get_chat_session_store] = lambda: store
    return TestClient(app)


def test_chat_message_without_session_id_creates_session() -> None:
    with client_with_store(ConversationSessionStore()) as client:
        response = client.post(
            "/api/v1/chat/message",
            json={"message": "help", "language": "en"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["session_id"]
    assert payload["intent"] == "help"
    assert payload["assistant_message"]


def test_chat_message_with_existing_session_continues_conversation() -> None:
    store = ConversationSessionStore()
    with client_with_store(store) as client:
        first = client.post(
            "/api/v1/chat/message",
            json={"message": "use 6 chips for forward prediction", "language": "en"},
        )
        session_id = first.json()["session_id"]
        second = client.post(
            "/api/v1/chat/message",
            json={"session_id": session_id, "message": "inlet 1 high", "language": "en"},
        )

    assert second.status_code == 200
    payload = second.json()
    assert payload["session_id"] == session_id
    assert payload["parameter_summary"]["chip_count"] == 6
    assert payload["parameter_summary"]["inlet1"] == 1.0
    assert payload["parameter_summary"]["inlet2"] == 0.0


def test_chat_rejects_empty_message() -> None:
    with client_with_store(ConversationSessionStore()) as client:
        response = client.post(
            "/api/v1/chat/message",
            json={"message": "", "language": "zh-CN"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_existing_forward_and_reverse_apis_remain_registered() -> None:
    with client_with_store(ConversationSessionStore()) as client:
        health = client.get("/api/v1/health")
        forward = client.post("/api/v1/forward", json={})
        reverse = client.post("/api/v1/reverse-tasks", json={})

    assert health.status_code == 200
    assert forward.status_code in {422, 503}
    assert reverse.status_code == 422
