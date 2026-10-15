from fastapi.testclient import TestClient

from app.main import app


def test_frontend_is_served_at_root():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Idra Chat" in response.text
    assert 'JSON.stringify(payload)' in response.text
    assert 'id="prompt"' in response.text
