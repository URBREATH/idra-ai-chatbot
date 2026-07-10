import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock


def test_chat_endpoint_returns_200_with_answer_sources_and_conversation_id():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["doc1"]],
        "distances": [[0.1]],
        "metadatas": [[{"tenant_id": "default-tenant", "dataset_id": "ds1", "title": "NO2 Air Quality", "publisher": "BEOPEN", "url": "https://a.com"}]],
        "documents": [["no2 anomalies in rome"]],
    }

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ollama.client.generate_completion", new=AsyncMock(return_value="Air quality shows NO2 anomalies.")):
                from app.main import app
                client = TestClient(app)

                response = client.post("/chat", json={
                    "message": "Show datasets about air quality",
                    "conversationId": "uuid-123"
                })

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Air quality shows NO2 anomalies."
    assert body["conversationId"] == "uuid-123"
    assert len(body["sources"]) == 1
    assert body["sources"][0]["datasetId"] == "ds1"
    assert body["sources"][0]["title"] == "NO2 Air Quality"


def test_chat_endpoint_generates_conversation_id_when_missing():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["doc1"]],
        "distances": [[0.1]],
        "metadatas": [[{"tenant_id": "default-tenant", "dataset_id": "ds1", "title": "T"}]],
        "documents": [["text"]],
    }

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ollama.client.generate_completion", new=AsyncMock(return_value="answer")):
                from app.main import app
                client = TestClient(app)

                response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert response.json()["conversationId"] is not None


def test_chat_endpoint_validates_message_field():
    from app.main import app
    client = TestClient(app)

    response = client.post("/chat", json={"message": "", "conversationId": "uuid-123"})
    assert response.status_code == 422


def test_chat_endpoint_validates_message_max_length():
    from app.main import app
    client = TestClient(app)

    response = client.post("/chat", json={"message": "x" * 5001})
    assert response.status_code == 422


def test_chat_endpoint_returns_fallback_on_no_results():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ollama.client.generate_completion", new=AsyncMock(return_value="SHOULD NOT BE CALLED")):
                from app.main import app
                client = TestClient(app)

                response = client.post("/chat", json={"message": "unknown topic"})

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert body["answer"] != "SHOULD NOT BE CALLED"
    assert body["conversationId"] is not None


def test_chat_endpoint_resolves_tenant_from_header():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection) as mock_get_coll:
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            from app.main import app
            client = TestClient(app)

            response = client.post("/chat", json={"message": "hi"}, headers={"x-tenant-id": "custom-tenant"})

    assert response.status_code == 200
    mock_get_coll.assert_called_with("custom-tenant")


def test_chat_history_endpoint_returns_messages():
    from app.main import app
    client = TestClient(app)

    response = client.get("/chat/uuid-123")
    assert response.status_code == 200
    body = response.json()
    assert "conversationId" in body
    assert "messages" in body
