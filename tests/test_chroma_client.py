import pytest
from unittest.mock import MagicMock, patch

def test_get_tenant_collection_creates_correct_name():
    with patch("app.chroma.client.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        from app.chroma.client import get_tenant_collection
        result = get_tenant_collection("test_tenant_123")
        
        mock_client.get_or_create_collection.assert_called_once_with(name="rag_tenant_test_tenant_123")

def test_get_tenant_collection_returns_collection():
    with patch("app.chroma.client.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        from app.chroma.client import get_tenant_collection
        result = get_tenant_collection("abc123")
        
        assert result == mock_collection

def test_chroma_url_defaults():
    with patch.dict("os.environ", {}, clear=True):
        import importlib
        import app.chroma.client as chroma_client
        importlib.reload(chroma_client)
        assert chroma_client.CHROMA_URL == "http://localhost:8000"