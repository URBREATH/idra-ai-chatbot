import pytest
from unittest.mock import patch, MagicMock, AsyncMock

@pytest.mark.asyncio
async def test_ingest_tenant_processes_datasets():
    mock_datasets = [
        {"_id": {"id": "ds1", "type": "Dataset"}, "title": "Dataset 1", "publisher": "BEOPEN"},
        {"_id": {"id": "ds2", "type": "Dataset"}, "description": "Description 2"}
    ]
    
    mock_collection = MagicMock()
    
    with patch("app.ingestion.service.get_datasets", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ingestion.service.get_tenant_collection", return_value=mock_collection):
                from app.ingestion.service import ingest_tenant
                ingest_tenant("tenant_abc")
                
                mock_collection.add.assert_called_once()
                call_args = mock_collection.add.call_args
                assert len(call_args[1]["ids"]) == 2

@pytest.mark.asyncio
async def test_ingest_tenant_skips_empty_text():
    mock_datasets = [
        {"_id": {"id": "ds1", "type": "Dataset"}},
        {"_id": {"id": "ds2", "type": "Dataset"}, "title": "Valid Dataset"}
    ]
    
    mock_collection = MagicMock()
    
    with patch("app.ingestion.service.get_datasets", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ingestion.service.get_tenant_collection", return_value=mock_collection):
                from app.ingestion.service import ingest_tenant
                ingest_tenant("tenant_abc")
                
                call_args = mock_collection.add.call_args
                assert len(call_args[1]["ids"]) == 1

@pytest.mark.asyncio
async def test_ingest_tenant_uses_dataset_id():
    mock_datasets = [
        {"_id": {"id": "urn:ngsi-ld:Dataset:123"}, "title": "Test Dataset"}
    ]
    
    mock_collection = MagicMock()
    
    with patch("app.ingestion.service.get_datasets", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ingestion.service.get_tenant_collection", return_value=mock_collection):
                from app.ingestion.service import ingest_tenant
                ingest_tenant("tenant_xyz")
                
                call_args = mock_collection.add.call_args
                assert "urn:ngsi-ld:Dataset:123" in call_args[1]["ids"]

@pytest.mark.asyncio
async def test_ingest_tenant_creates_correct_collection_name():
    mock_datasets = [{"_id": {"id": "ds1"}, "title": "Test"}]
    
    with patch("app.ingestion.service.get_datasets", new=AsyncMock(return_value=mock_datasets)):
        with patch("app.ingestion.service.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ingestion.service.get_tenant_collection") as mock_get_collection:
                mock_collection = MagicMock()
                mock_get_collection.return_value = mock_collection
                
                from app.ingestion.service import ingest_tenant
                ingest_tenant("my_tenant")
                
                mock_get_collection.assert_called_once_with("my_tenant")