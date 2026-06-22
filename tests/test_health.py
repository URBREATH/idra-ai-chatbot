import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    
    assert response.status_code == 200
    assert response.json()["status"] == "UP"
    assert "mongo" in response.json()
    assert "chroma" in response.json()
    assert "ollama" in response.json()

def test_health_response_structure():
    client = TestClient(app)
    response = client.get("/health")
    data = response.json()
    
    required_keys = ["status", "mongo", "chroma", "ollama"]
    for key in required_keys:
        assert key in data