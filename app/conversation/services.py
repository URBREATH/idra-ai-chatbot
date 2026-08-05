from app.conversation import repositories
from app.conversation.dto import ConversationMessageDTO, ConversationHistoryDTO
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


async def append_user_message(
    conversation_id: str,
    tenant_id: str,
    user_id: str,
    message_content: str,
) -> ConversationMessageDTO:
    """Save user message to conversation history."""
    doc = await repositories.save_message(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        user_id=user_id,
        role="user",
        content=message_content,
    )
    return ConversationMessageDTO(
        role=doc["role"],
        content=doc["content"],
        createdAt=doc["createdAt"],
    )


async def append_assistant_message(
    conversation_id: str,
    tenant_id: str,
    user_id: str,
    message_content: str,
) -> ConversationMessageDTO:
    """Save assistant message to conversation history."""
    doc = await repositories.save_message(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        user_id=user_id,
        role="assistant",
        content=message_content,
    )
    return ConversationMessageDTO(
        role=doc["role"],
        content=doc["content"],
        createdAt=doc["createdAt"],
    )


async def get_conversation(
    conversation_id: str,
    tenant_id: str,
) -> ConversationHistoryDTO:
    """Retrieve full conversation history."""
    messages_raw = await repositories.get_conversation_history(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
    )
    
    messages = [
        ConversationMessageDTO(
            role=m["role"],
            content=m["content"],
            createdAt=m["createdAt"],
        )
        for m in messages_raw
    ]
    
    owner_user_id = messages_raw[0].get("userId", "") if messages_raw else ""

    return ConversationHistoryDTO(
        conversationId=conversation_id,
        tenantId=tenant_id,
        userId=owner_user_id,
        messages=messages,
        createdAt=messages[0].createdAt if messages else datetime.now(timezone.utc),
        updatedAt=messages[-1].createdAt if messages else datetime.now(timezone.utc),
    )


async def get_context_for_llm(
    conversation_id: str,
    tenant_id: str,
    limit: int = 10,
) -> str:
    """
    Format conversation history as context string for LLM prompt injection.
    
    Returns formatted string like:
    User: [first message]
    Assistant: [response]
    User: [follow-up]
    ...
    """
    messages = await repositories.get_recent_messages_for_context(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        limit=limit,
    )
    
    if not messages:
        return ""
    
    context_lines = []
    for msg in messages:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        context_lines.append(f"{role_label}: {msg['content']}")
    
    return "\n".join(context_lines)
