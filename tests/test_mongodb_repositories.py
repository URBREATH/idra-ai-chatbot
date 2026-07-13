import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

@pytest.mark.asyncio
async def test_get_datasets_returns_list():
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"_id": {"id": "ds1", "type": "Dataset"}, "title": "Dataset 1"},
        {"_id": {"id": "ds2", "type": "Dataset"}, "title": "Dataset 2"}
    ])
    
    with patch("app.mongodb.repositories.db") as mock_db:
        mock_collection = MagicMock()
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_collection
        
        from app.mongodb.repositories import get_datasets
        result = await get_datasets()
        
        assert len(result) == 2
        assert result[0]["title"] == "Dataset 1"

@pytest.mark.asyncio
async def test_get_datasets_with_filter():
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"_id": {"id": "ds1", "type": "Dataset"}, "title": "Filtered Dataset"}
    ])
    
    with patch("app.mongodb.repositories.db") as mock_db:
        mock_collection = MagicMock()
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_collection
        
        from app.mongodb.repositories import get_datasets
        result = await get_datasets(filter_query={"publisher": "BEOPEN"})
        
        mock_collection.find.assert_called_once_with({"publisher": "BEOPEN"})

@pytest.mark.asyncio
async def test_get_datasets_empty_result():
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    
    with patch("app.mongodb.repositories.db") as mock_db:
        mock_collection = MagicMock()
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_collection
        
        from app.mongodb.repositories import get_datasets
        result = await get_datasets()
        
        assert result == []

@pytest.mark.asyncio
async def test_get_datasets_since():
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"_id": {"id": "ds1"}, "title": "New Dataset", "tenant_id": "tenant_abc"}
    ])
    
    with patch("app.mongodb.repositories.db") as mock_db:
        mock_collection = MagicMock()
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_collection
        
        from app.mongodb.repositories import get_datasets_since
        result = await get_datasets_since("tenant_abc", datetime(2024, 1, 1))
        
        mock_collection.find.assert_called_once()
        call_args = mock_collection.find.call_args[0][0]
        assert call_args["tenant_id"] == "tenant_abc"
        assert "$gte" in call_args["updatedAt"]

@pytest.mark.asyncio
async def test_get_datasets_by_ids():
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"_id": {"id": "ds1"}, "title": "Dataset 1"},
        {"_id": {"id": "ds2"}, "title": "Dataset 2"}
    ])
    
    with patch("app.mongodb.repositories.db") as mock_db:
        mock_collection = MagicMock()
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_collection
        
        from app.mongodb.repositories import get_datasets_by_ids
        result = await get_datasets_by_ids(["ds1", "ds2"])
        
        mock_collection.find.assert_called_once()
        call_args = mock_collection.find.call_args[0][0]
        assert "$in" in call_args["_id.id"]

@pytest.mark.asyncio
async def test_get_deleted_dataset_ids():
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"dataset_id": "ds1", "deletedAt": datetime(2024, 1, 1)},
        {"dataset_id": "ds2", "deletedAt": datetime(2024, 1, 2)}
    ])
    
    with patch("app.mongodb.repositories.db") as mock_db:
        mock_collection = MagicMock()
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_collection
        
        from app.mongodb.repositories import get_deleted_dataset_ids
        result = await get_deleted_dataset_ids("tenant_abc", datetime(2024, 1, 1))
        
        assert len(result) == 2
        assert "ds1" in result
        assert "ds2" in result

@pytest.mark.asyncio
async def test_get_all_dataset_ids():
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"_id": {"id": "ds1"}},
        {"_id": {"id": "ds2"}},
        {"_id": {"id": "ds3"}}
    ])
    
    with patch("app.mongodb.repositories.db") as mock_db:
        mock_collection = MagicMock()
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_collection
        
        from app.mongodb.repositories import get_all_dataset_ids
        result = await get_all_dataset_ids("tenant_abc")
        
        assert len(result) == 3
        assert "ds1" in result
        assert "ds2" in result
        assert "ds3" in result


@pytest.mark.asyncio
async def test_get_all_dataset_ids_filters_none():
    """Records without _id.id must be excluded from the result (Bug fix)."""
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {"_id": {"id": "ds1"}},
        {"_id": {}},             # missing id key
        {"_id": {"id": None}},  # explicit None
    ])

    with patch("app.mongodb.repositories.db") as mock_db:
        mock_collection = MagicMock()
        mock_collection.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_collection

        from app.mongodb.repositories import get_all_dataset_ids
        result = await get_all_dataset_ids("tenant_abc")

        assert result == ["ds1"]  # only valid id survives