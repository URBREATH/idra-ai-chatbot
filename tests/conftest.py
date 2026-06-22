import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_chroma_client():
    with patch("app.chroma.client.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client
        yield mock_collection

@pytest.fixture
def mock_ollama():
    with patch("app.ollama.client.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_response_embed = MagicMock()
        mock_response_embed.json.return_value = {"embedding": [0.1] * 1024}
        mock_response_embed.raise_for_status = MagicMock()
        
        mock_response_chat = MagicMock()
        mock_response_chat.json.return_value = {"message": {"content": "Test response"}}
        mock_response_chat.raise_for_status = MagicMock()
        
        mock_instance.__aenter__.return_value.post.side_effect = lambda url, json: mock_response_embed if "embeddings" in url else mock_response_chat
        mock_client.return_value = mock_instance
        yield mock_client

@pytest.fixture
def mock_mongodb():
    with patch("app.mongodb.client.get_database") as mock_get_db:
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list.return_value = [
            {"_id": {"id": "test-dataset-1", "type": "Dataset"}, "title": "Test Dataset", "description": "A test dataset"}
        ]
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_collection
        mock_get_db.return_value = mock_db
        yield mock_db

@pytest.fixture
def test_client():
    from app.main import app
    return TestClient(app)