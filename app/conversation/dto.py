from pydantic import BaseModel
from datetime import datetime


class ConversationMessageDTO(BaseModel):
    """Message stored in MongoDB conversation history"""
    role: str  # "user" or "assistant"
    content: str
    createdAt: datetime


class ConversationHistoryDTO(BaseModel):
    """Full conversation retrieved from MongoDB"""
    conversationId: str
    tenantId: str
    userId: str
    messages: list[ConversationMessageDTO]
    createdAt: datetime
    updatedAt: datetime
