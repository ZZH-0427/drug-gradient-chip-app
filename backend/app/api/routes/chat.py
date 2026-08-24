from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.routes.reverse import get_reverse_task_manager
from app.chat.schemas import ChatMessageRequest, ChatMessageResponse
from app.chat.service import ChatService
from app.chat.session import ConversationSessionStore
from app.core.model_state import ForwardModelState
from app.model_runtime.reverse_tasks import ReverseTaskManager


router = APIRouter(tags=["chat"])
_session_store = ConversationSessionStore()


def get_chat_session_store() -> ConversationSessionStore:
    return _session_store


def get_chat_service(
    request: Request,
    store: ConversationSessionStore = Depends(get_chat_session_store),
    reverse_manager: ReverseTaskManager = Depends(get_reverse_task_manager),
) -> ChatService:
    model_state = getattr(request.app.state, "forward_model", None)
    forward_adapter = model_state.adapter if isinstance(model_state, ForwardModelState) and model_state.ready else None
    return ChatService(
        sessions=store,
        forward_adapter=forward_adapter,
        reverse_manager=reverse_manager,
    )


@router.post("/chat/message", response_model=ChatMessageResponse)
def handle_chat_message(
    request: ChatMessageRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatMessageResponse:
    return service.handle_message(request)
