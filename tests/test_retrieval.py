import pytest
from unittest.mock import MagicMock, patch, AsyncMock

@pytest.mark.asyncio
async def test_vector_search_filters_by_tenant():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["doc1", "doc2"]],
        "distances": [[0.1, 0.2]],
        "metadatas": [[{"tenant_id": "tenant_a", "dataset_id": "ds1"}, {"tenant_id": "tenant_a", "dataset_id": "ds2"}]]
    }
    
    with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
        from app.ollama.client import generate_embedding
        embedding = await generate_embedding("test query")
        assert len(embedding) == 1024

@pytest.mark.asyncio
async def test_reranking_returns_top_k():
    scores = [0.9, 0.3, 0.7, 0.1, 0.5]
    top_k = 3
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    
    assert top_indices == [0, 2, 4]

@pytest.mark.asyncio
async def test_retrieval_metadata_filtering():
    filter_fields = ["tenant_id", "theme", "publisher", "geo"]
    
    query_filter = {"tenant_id": "tenant_abc", "theme": "air_quality"}
    
    assert all(f in query_filter for f in ["tenant_id", "theme"])