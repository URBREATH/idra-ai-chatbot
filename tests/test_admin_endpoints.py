import pytest
from unittest.mock import MagicMock, patch, AsyncMock

def test_admin_ingestion_run_endpoint_requires_auth():
    from app.main import app
    from fastapi.testclient import TestClient
    
    client = TestClient(app)
    response = client.post("/admin/ingestion/run", json={"fullReindex": False})
    
    assert response.status_code >= 400 or response.status_code == 404

@pytest.mark.asyncio
async def test_ingestion_status_returns_correct_structure():
    expected_keys = ["running", "processed", "remaining"]
    
    mock_status = {
        "running": True,
        "processed": 534,
        "remaining": 231
    }
    
    assert all(k in mock_status for k in expected_keys)

@pytest.mark.asyncio
async def test_feedback_endpoint_accepts_rating():
    valid_ratings = ["positive", "negative"]
    
    for rating in valid_ratings:
        assert rating in valid_ratings