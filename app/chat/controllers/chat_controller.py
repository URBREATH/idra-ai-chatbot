import os

from fastapi import APIRouter, Header

from app.chat.dto.models import ChatRequest, ChatResponse, ConversationHistory
from app.chat.services.chat_service import generate_answer

router = APIRouter()

DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "default-tenant")


def _resolve_tenant(x_tenant_id: str | None) -> str:
    """Resolve the tenant identifier before retrieval (FOLDER_STRUCTURE.md rule 7)."""
    return x_tenant_id or DEFAULT_TENANT_ID


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, x_tenant_id: str | None = Header(default=None)):
    tenant_id = _resolve_tenant(x_tenant_id)
    return await generate_answer(
        message=request.message,
        conversation_id=request.conversationId,
        tenant_id=tenant_id,
    )


@router.get("/chat/{conversation_id}", response_model=ConversationHistory)
async def get_conversation_history(conversation_id: str):
    return ConversationHistory(conversationId=conversation_id, messages=[])
