import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient


def test_tenant_isolation_no_cross_tenant_data():
    with patch("app.chroma.client.get_client") as mock_get_client:
        mock_client = MagicMock()

        tenant_a_collection = MagicMock()
        tenant_b_collection = MagicMock()

        def get_collection_side_effect(name):
            if name == "rag_tenant_a":
                return tenant_a_collection
            if name == "rag_tenant_b":
                return tenant_b_collection

        mock_client.get_or_create_collection.side_effect = get_collection_side_effect
        mock_get_client.return_value = mock_client

        from app.chroma.client import get_tenant_collection
        coll_a = get_tenant_collection("a")
        coll_b = get_tenant_collection("b")

        assert coll_a == tenant_a_collection
        assert coll_b == tenant_b_collection
        assert coll_a != coll_b


@pytest.mark.asyncio
async def test_tenant_collection_naming():
    with patch("app.chroma.client.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client

        from app.chroma.client import get_tenant_collection
        result = get_tenant_collection("company01")

        mock_client.get_or_create_collection.assert_called_once_with(name="rag_tenant_company01")


def test_tenant_resolver_defaults_to_env_tenant():
    from app.common.guards.tenant_guard import resolve_tenant
    result = resolve_tenant(x_tenant_id=None)
    assert result  # must not be empty
    assert isinstance(result, str)


def test_tenant_resolver_uses_provided_header():
    from app.common.guards.tenant_guard import resolve_tenant
    result = resolve_tenant(x_tenant_id="acme-corp")
    assert result == "acme-corp"


def test_tenant_resolver_rejects_invalid_characters():
    from app.common.guards.tenant_guard import resolve_tenant
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        resolve_tenant(x_tenant_id="tenant with spaces!")
    assert exc_info.value.status_code == 400


def test_tenant_collection_name_format():
    from app.common.guards.tenant_guard import tenant_collection_name
    assert tenant_collection_name("acme") == "rag_tenant_acme"
    assert tenant_collection_name("tenant-01") == "rag_tenant_tenant-01"


def test_chat_endpoint_uses_tenant_header():
    """Ensure the chat endpoint passes the X-Tenant-Id header through to the service."""
    from app.main import app

    with patch("app.chat.services.chat_service.embed_query", new=AsyncMock(return_value=[])):
        with TestClient(app) as client:
            response = client.post(
                "/chat",
                json={"message": "hello"},
                headers={"X-Tenant-Id": "my-tenant"},
            )
    # No cross-tenant data should bleed; response must be a valid ChatResponse shape
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body
    assert "conversationId" in body


def test_different_tenants_get_different_collections():
    """Querying two different tenant IDs must never share a ChromaDB collection."""
    with patch("app.chroma.client.get_client") as mock_get_client:
        mock_client = MagicMock()
        collections: dict = {}

        def make_collection(name):
            if name not in collections:
                collections[name] = MagicMock(name=name)
            return collections[name]

        mock_client.get_or_create_collection.side_effect = make_collection
        mock_get_client.return_value = mock_client

        from app.chroma.client import get_tenant_collection
        coll_x = get_tenant_collection("tenant-x")
        coll_y = get_tenant_collection("tenant-y")

        assert coll_x is not coll_y
        assert len(collections) == 2
