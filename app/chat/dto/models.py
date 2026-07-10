from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    title: str
    datasetId: str
    publisher: str | None = None
    url: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    conversationId: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    conversationId: str | None = None


class ConversationMessage(BaseModel):
    role: str
    content: str
    createdAt: str | None = None


class ConversationHistory(BaseModel):
    conversationId: str
    messages: list[ConversationMessage]
