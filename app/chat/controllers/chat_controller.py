import uuid

from fastapi import APIRouter, Header
from app.ollama import client as ollama_client

from app.chat.dto.models import ChatRequest, ChatResponse, ConversationHistory
from app.chat.services.chat_service import generate_answer
from app.common.guards.tenant_guard import resolve_tenant
from app.auth import extract_user_id_from_keycloak_token
from app.conversation import services as conversation_services

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    x_tenant_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    """
    Chat endpoint with conversation history persistence.
    
    - Extracts user ID from Keycloak JWT
    - Saves user message to MongoDB
    - Generates answer with context from previous messages
    - Saves assistant response to MongoDB
    - Returns answer + sources + conversation ID
    """
    tenant_id = resolve_tenant(x_tenant_id)
    user_id = extract_user_id_from_keycloak_token(authorization)
    
    # Use provided conversation ID or create new one
    conversation_id = request.conversationId or str(uuid.uuid4())
    
    # Save user message to history
    await conversation_services.append_user_message(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        user_id=user_id,
        message_content=request.message,
    )
    
    # Generate answer (with conversation context)
    response = await generate_answer(
        message=request.message,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        user_id=user_id,
        model=request.model,
    )
    
    # Save assistant response to history
    await conversation_services.append_assistant_message(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        user_id=user_id,
        message_content=response.answer,
    )
    
    # Ensure response includes conversation ID
    response.conversationId = conversation_id
    return response


@router.get("/models")
async def list_available_models():
    return {"models": await ollama_client.list_models()}


@router.get("/chat/{conversation_id}", response_model=ConversationHistory)
async def get_conversation_history(
    conversation_id: str,
    x_tenant_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    """
    Retrieve full conversation history for a given conversation ID.
    Only the conversation owner can retrieve it (via userId from JWT).
    """
    tenant_id = resolve_tenant(x_tenant_id)
    user_id = extract_user_id_from_keycloak_token(authorization)
    
    # Get conversation from MongoDB
    conversation = await conversation_services.get_conversation(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
    )
    
    if not conversation.messages:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Verify user owns this conversation
    if conversation.userId and conversation.userId != user_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Access denied: conversation belongs to another user")

    messages = [
        {
            "role": msg.role,
            "content": msg.content,
            "createdAt": msg.createdAt.isoformat() if msg.createdAt else None,
        }
        for msg in conversation.messages
    ]
    
    return ConversationHistory(
        conversationId=conversation_id,
        messages=messages,
    )
