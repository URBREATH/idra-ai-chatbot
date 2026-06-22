import pytest
from unittest.mock import MagicMock, patch, AsyncMock

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