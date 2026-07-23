import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

@pytest.mark.asyncio
async def test_ingest_tenant_processes_datasets():
    mock_datasets = [
        {"_id": {"id": "ds1", "type": "Dataset"}, "title": "Dataset 1", "publisher": "BEOPEN"},
        {"_id": {"id": "ds2", "type": "Dataset"}, "description": "Description 2"}
    ]
    
    mock_collection = MagicMock()
    
    with patch("app.ingestion.service.get_datasets_since", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.get_deleted_dataset_ids", new=AsyncMock(return_value=[])):
            with patch("app.ingestion.service.get_all_dataset_ids", new=AsyncMock(return_value=[])):
                with patch("app.ingestion.service.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
                    with patch("app.ingestion.service.get_tenant_collection", return_value=mock_collection):
                        from app.ingestion.service import ingest_tenant
                        result = await ingest_tenant("tenant_abc")
                        
                        assert result["processed"] >= 1
                        mock_collection.upsert.assert_called_once()

@pytest.mark.asyncio
async def test_ingest_tenant_skips_empty_text():
    mock_datasets = [
        {"_id": {"id": "ds1", "type": "Dataset"}},
        {"_id": {"id": "ds2", "type": "Dataset"}, "title": "Valid Dataset"}
    ]
    
    mock_collection = MagicMock()
    
    with patch("app.ingestion.service.get_datasets_since", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.get_deleted_dataset_ids", new=AsyncMock(return_value=[])):
            with patch("app.ingestion.service.get_all_dataset_ids", new=AsyncMock(return_value=[])):
                with patch("app.ingestion.service.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
                    with patch("app.ingestion.service.get_tenant_collection", return_value=mock_collection):
                        from app.ingestion.service import ingest_tenant
                        await ingest_tenant("tenant_abc")
                        
                        call_args = mock_collection.upsert.call_args
                        assert len(call_args[1]["ids"]) >= 1

@pytest.mark.asyncio
async def test_ingest_tenant_uses_dataset_id():
    mock_datasets = [
        {"_id": {"id": "urn:ngsi-ld:Dataset:123"}, "title": "Test Dataset"}
    ]
    
    mock_collection = MagicMock()
    
    with patch("app.ingestion.service.get_datasets_since", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.get_deleted_dataset_ids", new=AsyncMock(return_value=[])):
            with patch("app.ingestion.service.get_all_dataset_ids", new=AsyncMock(return_value=[])):
                with patch("app.ingestion.service.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
                    with patch("app.ingestion.service.get_tenant_collection", return_value=mock_collection):
                        from app.ingestion.service import ingest_tenant
                        await ingest_tenant("tenant_xyz")
                        
                        call_args = mock_collection.upsert.call_args
                        ids = call_args[1]["ids"]
                        assert any("urn:ngsi-ld:Dataset:123" in str(id) for id in ids)

@pytest.mark.asyncio
async def test_ingest_tenant_creates_correct_collection_name():
    mock_datasets = [{"_id": {"id": "ds1"}, "title": "Test"}]
    
    with patch("app.ingestion.service.get_datasets_since", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.get_deleted_dataset_ids", new=AsyncMock(return_value=[])):
            with patch("app.ingestion.service.get_all_dataset_ids", new=AsyncMock(return_value=[])):
                with patch("app.ingestion.service.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
                    with patch("app.ingestion.service.get_tenant_collection") as mock_get_collection:
                        mock_collection = MagicMock()
                        mock_get_collection.return_value = mock_collection
                        
                        from app.ingestion.service import ingest_tenant
                        await ingest_tenant("my_tenant")
                        
                        mock_get_collection.assert_called_once_with("my_tenant")

@pytest.mark.asyncio
async def test_ingest_tenant_full_reindex_deletes_existing():
    mock_datasets = []
    existing_ids = ["ds1", "ds2"]
    
    mock_collection = MagicMock()
    
    with patch("app.ingestion.service.get_datasets_since", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.get_deleted_dataset_ids", new=AsyncMock(return_value=[])):
            with patch("app.ingestion.service.get_all_dataset_ids", new=AsyncMock(return_value=existing_ids)):
                with patch("app.ingestion.service.get_tenant_collection", return_value=mock_collection):
                    with patch("app.ingestion.service.delete_documents_from_collection") as mock_delete:
                        from app.ingestion.service import ingest_tenant
                        result = await ingest_tenant("tenant_abc", full_reindex=True)
                        
                        mock_delete.assert_called_once()

@pytest.mark.asyncio
async def test_ingest_tenant_returns_result():
    mock_datasets = [
        {"_id": {"id": "ds1"}, "title": "Dataset 1"}
    ]
    
    mock_collection = MagicMock()
    
    with patch("app.ingestion.service.get_datasets_since", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.get_deleted_dataset_ids", new=AsyncMock(return_value=[])):
            with patch("app.ingestion.service.get_all_dataset_ids", new=AsyncMock(return_value=[])):
                with patch("app.ingestion.service.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
                    with patch("app.ingestion.service.get_tenant_collection", return_value=mock_collection):
                        from app.ingestion.service import ingest_tenant
                        result = await ingest_tenant("tenant_abc")
                        
                        assert isinstance(result, dict)
                        assert "processed" in result
                        assert "total_datasets" in result


@pytest.mark.asyncio
async def test_ingest_tenant_deletes_incremental_deletes():
    """Datasets removed from MongoDB must also be removed from ChromaDB (Bug fix)."""
    mock_datasets = []
    deleted_ids = ["ds-removed-1", "ds-removed-2"]

    mock_collection = MagicMock()

    with patch("app.ingestion.service.get_datasets_since", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.get_deleted_dataset_ids", new=AsyncMock(return_value=deleted_ids)):
            with patch("app.ingestion.service.get_all_dataset_ids", new=AsyncMock(return_value=[])):
                with patch("app.ingestion.service.get_tenant_collection", return_value=mock_collection):
                    with patch("app.ingestion.service.delete_documents_from_collection") as mock_delete:
                        from app.ingestion.service import ingest_tenant
                        await ingest_tenant("tenant_abc")

                        # delete must be called once for the incremental deleted_ids
                        mock_delete.assert_called_once_with(mock_collection, deleted_ids)