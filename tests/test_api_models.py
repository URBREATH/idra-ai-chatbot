import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.main import ChatRequest, ChatResponse, SourceReference

def test_chat_request_valid():
    request = ChatRequest(message="Show datasets about air quality", conversationId="uuid-123")
    assert request.message == "Show datasets about air quality"
    assert request.conversationId == "uuid-123"

def test_chat_request_without_conversation_id():
    request = ChatRequest(message="Test query")
    assert request.message == "Test query"
    assert request.conversationId is None

def test_chat_response_model():
    response = ChatResponse(
        answer="Several datasets are available.",
        sources=[
            SourceReference(title="NO2 air quality", datasetId="urn:dataset:123", publisher="BEOPEN", url="https://example.com")
        ],
        conversationId="uuid-123"
    )
    assert response.answer == "Several datasets are available."
    assert len(response.sources) == 1
    assert response.conversationId == "uuid-123"

def test_source_reference_optional_fields():
    source = SourceReference(title="Dataset", datasetId="id-1")
    assert source.publisher is None
    assert source.url is None