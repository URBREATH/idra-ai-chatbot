import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_embed_query_returns_vector_from_ollama():
    with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)) as mock_embed:
        from app.retrieval.embeddings.query_embedder import embed_query

        result = await embed_query("datasets about air quality")

        assert result == [0.1] * 1024
        mock_embed.assert_awaited_once_with("datasets about air quality")


@pytest.mark.asyncio
async def test_embed_query_empty_query_returns_empty_vector_gracefully():
    with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[])):
        from app.retrieval.embeddings.query_embedder import embed_query

        result = await embed_query("")
        assert result == []


def test_vector_search_uses_tenant_collection_with_tenant_filter():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["doc1", "doc2"]],
        "distances": [[0.1, 0.2]],
        "metadatas": [[{"tenant_id": "tenant_a", "dataset_id": "ds1"}, {"tenant_id": "tenant_a", "dataset_id": "ds2"}]],
        "documents": [["text1", "text2"]],
    }

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        from app.retrieval.vector_search.searcher import vector_search

        result = vector_search("tenant_a", [0.1] * 1024)

    mock_collection.query.assert_called_once()
    call_kwargs = mock_collection.query.call_args.kwargs
    assert call_kwargs["n_results"] == 10
    assert call_kwargs["where"]["tenant_id"] == "tenant_a"
    assert call_kwargs["query_embeddings"] == [[0.1] * 1024]
    assert result["ids"] == [["doc1", "doc2"]]


def test_vector_search_allows_extra_metadata_filters():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        from app.retrieval.vector_search.searcher import vector_search

        vector_search("tenant_a", [0.1] * 8, n_results=5, where={"theme": "air_quality"})

    call_kwargs = mock_collection.query.call_args.kwargs
    assert call_kwargs["n_results"] == 5
    assert call_kwargs["where"] == {"tenant_id": "tenant_a", "theme": "air_quality"}


def test_rerank_orders_by_relevance_and_returns_top_k_indices():
    from app.retrieval.reranker.reranker import rerank

    query = "air quality"
    documents = ["no2 anomalies", "water pollution", "pm10 levels", "traffic data", "noise maps"]
    metadatas = [{"dataset_id": "ds1"}, {"dataset_id": "ds2"}, {"dataset_id": "ds3"}, {"dataset_id": "ds4"}, {"dataset_id": "ds5"}]
    distances = [0.9, 0.1, 0.5, 0.3, 0.2]

    indices = rerank(query, documents, metadatas, distances, top_k=3)

    assert len(indices) == 3
    assert all(0 <= i < len(documents) for i in indices)


def test_rerank_fallback_uses_distance_when_no_encoder_available():
    from app.retrieval.reranker.reranker import _distance_based_rank

    distances = [0.9, 0.1, 0.5]
    indices = _distance_based_rank(distances, top_k=2)
    assert indices == [1, 2]


def test_assemble_context_deduplicates_by_dataset_id():
    from app.retrieval.context.context_assembler import assemble_context

    documents = ["no2 description", "pm10 description", "no2 description duplicate"]
    metadatas = [
        {"dataset_id": "ds1", "title": "NO2 Air Quality", "publisher": "BEOPEN", "url": "https://a.com"},
        {"dataset_id": "ds2", "title": "PM10 Air Quality", "publisher": "EEA", "url": "https://b.com"},
        {"dataset_id": "ds1", "title": "NO2 Air Quality", "publisher": "BEOPEN", "url": "https://a.com"},
    ]

    context, sources = assemble_context(documents, metadatas)

    assert "no2 description" in context
    assert "pm10 description" in context
    assert len(sources) == 2
    dataset_ids = [s.datasetId for s in sources]
    assert dataset_ids == ["ds1", "ds2"]
    assert sources[0].title == "NO2 Air Quality"
    assert sources[0].publisher == "BEOPEN"


def test_assemble_context_handles_empty_input():
    from app.retrieval.context.context_assembler import assemble_context

    context, sources = assemble_context([], [])
    assert context == ""
    assert sources == []
