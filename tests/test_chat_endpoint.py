from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.chat.dto.models import ChatResponse
from app.conversation.dto import ConversationHistoryDTO, ConversationMessageDTO


@pytest.fixture(autouse=True)
def admin_token(monkeypatch):
    # auth is a plain admin token: the token value doubles as user_id
    monkeypatch.setenv("ADMIN_TOKEN", "user-1")


def _build_client():
    from app.main import app

    return TestClient(app)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_chat_endpoint_returns_200_with_answer_sources_and_conversation_id():
    mocked_answer = ChatResponse(answer="Air quality shows NO2 anomalies.", sources=[])

    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with patch("app.chat.controllers.chat_controller.generate_answer", new=AsyncMock(return_value=mocked_answer)) as mock_generate:
            with patch("app.chat.controllers.chat_controller.conversation_services.append_user_message", new=AsyncMock()) as mock_append_user:
                with patch("app.chat.controllers.chat_controller.conversation_services.append_assistant_message", new=AsyncMock()) as mock_append_assistant:
                    with _build_client() as client:
                        response = client.post(
                            "/chat",
                            json={"message": "Show datasets about air quality", "conversationId": "uuid-123", "userId": "user-1"},
                            headers={"Authorization": "Bearer user-1"},
                        )

    # NOTE: the controller no longer persists messages itself — the real
    # generate_answer() does it internally (covered by chat service tests).
    mock_generate.assert_awaited_once_with(
        message="Show datasets about air quality",
        conversation_id="uuid-123",
        tenant_id="default-tenant",
        user_id="user-1",
        model=None,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Air quality shows NO2 anomalies."
    assert body["conversationId"] == "uuid-123"
    assert body["sources"] == []


def test_chat_endpoint_generates_conversation_id_when_missing():
    mocked_answer = ChatResponse(answer="answer", sources=[])

    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with patch("app.chat.controllers.chat_controller.generate_answer", new=AsyncMock(return_value=mocked_answer)):
            with patch("app.chat.controllers.chat_controller.conversation_services.append_user_message", new=AsyncMock()):
                with patch("app.chat.controllers.chat_controller.conversation_services.append_assistant_message", new=AsyncMock()):
                    with _build_client() as client:
                        response = client.post(
                            "/chat",
                            json={"message": "hello"},
                            headers={"Authorization": "Bearer user-1"},
                        )

    assert response.status_code == 200
    assert response.json()["conversationId"] is not None


def test_chat_endpoint_validates_message_field():
    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with _build_client() as client:
            response = client.post("/chat", json={"message": "", "conversationId": "uuid-123"})
    assert response.status_code == 422


def test_chat_endpoint_validates_message_max_length():
    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with _build_client() as client:
            response = client.post("/chat", json={"message": "x" * 5001})
    assert response.status_code == 422


def test_chat_endpoint_requires_authorization_header():
    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with _build_client() as client:
            response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 401


def test_chat_endpoint_resolves_tenant_from_header():
    mocked_answer = ChatResponse(answer="fallback", sources=[])

    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with patch("app.chat.controllers.chat_controller.generate_answer", new=AsyncMock(return_value=mocked_answer)) as mock_generate:
            with _build_client() as client:
                response = client.post(
                    "/chat",
                    json={"message": "hi"},
                    headers={"Authorization": "Bearer user-1", "x-tenant-id": "custom-tenant"},
                )

    assert response.status_code == 200
    assert mock_generate.await_args.kwargs["tenant_id"] == "custom-tenant"


def test_chat_history_endpoint_returns_messages_for_owner():
    conversation = ConversationHistoryDTO(
        conversationId="uuid-123",
        tenantId="default-tenant",
        userId="user-1",
        messages=[
            ConversationMessageDTO(role="user", content="hello", createdAt=_utc_now()),
            ConversationMessageDTO(role="assistant", content="hi", createdAt=_utc_now()),
        ],
        createdAt=_utc_now(),
        updatedAt=_utc_now(),
    )

    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with patch("app.chat.controllers.chat_controller.conversation_services.get_conversation", new=AsyncMock(return_value=conversation)):
                with _build_client() as client:
                    response = client.get(
                        "/chat/uuid-123",
                        headers={"Authorization": "Bearer user-1"},
                    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversationId"] == "uuid-123"
    assert len(body["messages"]) == 2


def test_chat_history_endpoint_returns_403_for_non_owner():
    conversation = ConversationHistoryDTO(
        conversationId="uuid-123",
        tenantId="default-tenant",
        userId="user-owner",
        messages=[ConversationMessageDTO(role="user", content="secret", createdAt=_utc_now())],
        createdAt=_utc_now(),
        updatedAt=_utc_now(),
    )

    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with patch("app.chat.controllers.chat_controller.conversation_services.get_conversation", new=AsyncMock(return_value=conversation)):
                with _build_client() as client:
                    response = client.get(
                        "/chat/uuid-123",
                        headers={"Authorization": "Bearer user-1"},
                    )

    assert response.status_code == 403


def test_chat_history_endpoint_returns_404_when_conversation_not_found():
    empty_conversation = ConversationHistoryDTO(
        conversationId="uuid-123",
        tenantId="default-tenant",
        userId="",
        messages=[],
        createdAt=_utc_now(),
        updatedAt=_utc_now(),
    )

    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with patch("app.chat.controllers.chat_controller.conversation_services.get_conversation", new=AsyncMock(return_value=empty_conversation)):
                with _build_client() as client:
                    response = client.get(
                        "/chat/uuid-123",
                        headers={"Authorization": "Bearer user-1"},
                    )

    assert response.status_code == 404
