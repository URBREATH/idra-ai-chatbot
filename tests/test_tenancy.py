import pytest
from unittest.mock import MagicMock, patch, AsyncMock

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