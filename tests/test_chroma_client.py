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

def test_delete_documents_from_collection():
    mock_collection = MagicMock()

    from app.chroma.client import delete_documents_from_collection
    delete_documents_from_collection(mock_collection, ["ds1", "ds2"])

    # One delete call per dataset_id using `where` filter
    assert mock_collection.delete.call_count == 2
    calls = [c.kwargs for c in mock_collection.delete.call_args_list]
    dataset_ids_deleted = {c["where"]["dataset_id"] for c in calls}
    assert dataset_ids_deleted == {"ds1", "ds2"}


def test_delete_documents_from_collection_empty():
    mock_collection = MagicMock()

    from app.chroma.client import delete_documents_from_collection
    delete_documents_from_collection(mock_collection, [])

    mock_collection.delete.assert_not_called()


def test_delete_documents_from_collection_skips_none():
    mock_collection = MagicMock()

    from app.chroma.client import delete_documents_from_collection
    delete_documents_from_collection(mock_collection, ["ds1", None, "ds3"])

    # None must be skipped; only ds1 and ds3 should be deleted
    assert mock_collection.delete.call_count == 2
    calls = [c.kwargs for c in mock_collection.delete.call_args_list]
    dataset_ids_deleted = {c["where"]["dataset_id"] for c in calls}
    assert dataset_ids_deleted == {"ds1", "ds3"}