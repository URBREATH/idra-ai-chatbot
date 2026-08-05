from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.chat.dto.models import ChatResponse
from app.conversation.dto import ConversationHistoryDTO, ConversationMessageDTO


def _build_client():
    from app.main import app

    return TestClient(app)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def test_chat_endpoint_returns_200_with_answer_sources_and_conversation_id():
    mocked_answer = ChatResponse(answer="Air quality shows NO2 anomalies.", sources=[])

    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with patch("app.chat.controllers.chat_controller.extract_user_id_from_keycloak_token", return_value="user-1"):
            with patch("app.chat.controllers.chat_controller.generate_answer", new=AsyncMock(return_value=mocked_answer)) as mock_generate:
                with patch("app.chat.controllers.chat_controller.conversation_services.append_user_message", new=AsyncMock()) as mock_append_user:
                    with patch("app.chat.controllers.chat_controller.conversation_services.append_assistant_message", new=AsyncMock()) as mock_append_assistant:
                        with _build_client() as client:
                            response = client.post(
                                "/chat",
                                json={"message": "Show datasets about air quality", "conversationId": "uuid-123"},
                                headers={"Authorization": "Bearer test-token"},
                            )

    mock_append_user.assert_awaited_once_with(
        conversation_id="uuid-123",
        tenant_id="default-tenant",
        user_id="user-1",
        message_content="Show datasets about air quality",
    )
    mock_generate.assert_awaited_once_with(
        message="Show datasets about air quality",
        conversation_id="uuid-123",
        tenant_id="default-tenant",
        user_id="user-1",
        model=None,
    )
    mock_append_assistant.assert_awaited_once_with(
        conversation_id="uuid-123",
        tenant_id="default-tenant",
        user_id="user-1",
        message_content="Air quality shows NO2 anomalies.",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Air quality shows NO2 anomalies."
    assert body["conversationId"] == "uuid-123"
    assert body["sources"] == []


def test_chat_endpoint_generates_conversation_id_when_missing():
    mocked_answer = ChatResponse(answer="answer", sources=[])

    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()):
        with patch("app.chat.controllers.chat_controller.extract_user_id_from_keycloak_token", return_value="user-1"):
            with patch("app.chat.controllers.chat_controller.generate_answer", new=AsyncMock(return_value=mocked_answer)):
                with patch("app.chat.controllers.chat_controller.conversation_services.append_user_message", new=AsyncMock()):
                    with patch("app.chat.controllers.chat_controller.conversation_services.append_assistant_message", new=AsyncMock()):
                        with _build_client() as client:
                            response = client.post(
                                "/chat",
                                json={"message": "hello"},
                                headers={"Authorization": "Bearer test-token"},
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
        with patch("app.chat.controllers.chat_controller.extract_user_id_from_keycloak_token", return_value="user-1"):
            with patch("app.chat.controllers.chat_controller.generate_answer", new=AsyncMock(return_value=mocked_answer)):
                with patch("app.chat.controllers.chat_controller.conversation_services.append_assistant_message", new=AsyncMock()):
                    with patch("app.chat.controllers.chat_controller.conversation_services.append_user_message", new=AsyncMock()) as mock_append_user:
                        with _build_client() as client:
                            response = client.post(
                                "/chat",
                                json={"message": "hi"},
                                headers={"Authorization": "Bearer test-token", "x-tenant-id": "custom-tenant"},
                            )

    assert response.status_code == 200
    assert mock_append_user.await_args.kwargs["tenant_id"] == "custom-tenant"


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
        with patch("app.chat.controllers.chat_controller.extract_user_id_from_keycloak_token", return_value="user-1"):
            with patch("app.chat.controllers.chat_controller.conversation_services.get_conversation", new=AsyncMock(return_value=conversation)):
                with _build_client() as client:
                    response = client.get(
                        "/chat/uuid-123",
                        headers={"Authorization": "Bearer test-token"},
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
        with patch("app.chat.controllers.chat_controller.extract_user_id_from_keycloak_token", return_value="other-user"):
            with patch("app.chat.controllers.chat_controller.conversation_services.get_conversation", new=AsyncMock(return_value=conversation)):
                with _build_client() as client:
                    response = client.get(
                        "/chat/uuid-123",
                        headers={"Authorization": "Bearer test-token"},
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
        with patch("app.chat.controllers.chat_controller.extract_user_id_from_keycloak_token", return_value="user-1"):
            with patch("app.chat.controllers.chat_controller.conversation_services.get_conversation", new=AsyncMock(return_value=empty_conversation)):
                with _build_client() as client:
                    response = client.get(
                        "/chat/uuid-123",
                        headers={"Authorization": "Bearer test-token"},
                    )

    assert response.status_code == 404
