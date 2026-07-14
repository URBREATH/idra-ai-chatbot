import os

from fastapi import APIRouter, Header
from app.ollama import client as ollama_client

from app.chat.dto.models import ChatRequest, ChatResponse, ConversationHistory
from app.chat.services.chat_service import generate_answer
from app.common.guards.tenant_guard import resolve_tenant

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, x_tenant_id: str | None = Header(default=None)):
    tenant_id = resolve_tenant(x_tenant_id)
    return await generate_answer(
        message=request.message,
        conversation_id=request.conversationId,
        tenant_id=tenant_id,
        model=request.model,
    )

@router.get("/models")
async def list_available_models():
    return {"models": await ollama_client.list_models()}

@router.get("/chat/{conversation_id}", response_model=ConversationHistory)
async def get_conversation_history(conversation_id: str):
    return ConversationHistory(conversationId=conversation_id, messages=[])
