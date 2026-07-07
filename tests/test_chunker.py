import pytest
from unittest.mock import AsyncMock, patch


class TestChunker:
    @pytest.mark.asyncio
    async def test_chunk_splits_by_sdmx_dimension(self):
        from app.ingestion.chunker import chunk_payload

        payload = "[SEMANTIC BLOCK] occupazione lavoro [SEP] [TECHNICAL BLOCK] FREQ A M GEO IT FR INDICATOR EMP_RATE [SEP] [DESCRIPTION BLOCK] Title: Test"
        dataset_id = "ds123"

        chunks = await chunk_payload(payload, dataset_id)

        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk["dataset_id"] == dataset_id
            assert "chunk_id" in chunk
            assert "text" in chunk
            assert "FREQ" in chunk["text"] or "GEO" in chunk["text"] or "INDICATOR" in chunk["text"]

    @pytest.mark.asyncio
    async def test_chunk_keeps_same_dataset_id(self):
        from app.ingestion.chunker import chunk_payload

        payload = "[SEMANTIC BLOCK] a [SEP] [TECHNICAL BLOCK] FREQ A M GEO IT [SEP] [DESCRIPTION BLOCK] desc"
        dataset_id = "urn:ngsi-ld:Dataset:456"

        chunks = await chunk_payload(payload, dataset_id)

        for chunk in chunks:
            assert chunk["dataset_id"] == dataset_id

    @pytest.mark.asyncio
    async def test_chunk_respects_token_limit(self):
        from app.ingestion.chunker import chunk_payload

        # Create a large payload that will need chunking
        large_technical = " ".join([f"DIM{i} " + " ".join([f"CODE{j}" for j in range(50)]) for i in range(20)])
        payload = f"[SEMANTIC BLOCK] terms [SEP] [TECHNICAL BLOCK] {large_technical} [SEP] [DESCRIPTION BLOCK] desc"
        dataset_id = "ds1"

        chunks = await chunk_payload(payload, dataset_id)

        for chunk in chunks:
            # Rough check: each chunk should be under ~512 tokens (~2000 chars)
            assert len(chunk["text"]) < 3000

    @pytest.mark.asyncio
    async def test_chunk_single_dimension_fits(self):
        from app.ingestion.chunker import chunk_payload

        payload = "[SEMANTIC BLOCK] occ [SEP] [TECHNICAL BLOCK] FREQ A [SEP] [DESCRIPTION BLOCK] desc"
        dataset_id = "ds1"

        chunks = await chunk_payload(payload, dataset_id)

        assert len(chunks) == 1
        assert chunks[0]["chunk_id"] == "ds1_chunk_1"

    @pytest.mark.asyncio
    async def test_chunk_ids_are_sequential(self):
        from app.ingestion.chunker import chunk_payload

        large_technical = " ".join([f"DIM{i} CODE1 CODE2" for i in range(30)])
        payload = f"[SEMANTIC BLOCK] occ [SEP] [TECHNICAL BLOCK] {large_technical} [SEP] [DESCRIPTION BLOCK] desc"
        dataset_id = "ds1"

        chunks = await chunk_payload(payload, dataset_id)

        for i, chunk in enumerate(chunks):
            assert chunk["chunk_id"] == f"ds1_chunk_{i+1}"

    @pytest.mark.asyncio
    async def test_chunk_preserves_semantic_and_description(self):
        from app.ingestion.chunker import chunk_payload

        payload = "[SEMANTIC BLOCK] occupazione lavoro [SEP] [TECHNICAL BLOCK] FREQ A M GEO IT [SEP] [DESCRIPTION BLOCK] Title: Test | Description: Test desc"
        dataset_id = "ds1"

        chunks = await chunk_payload(payload, dataset_id)

        for chunk in chunks:
            assert "[SEMANTIC BLOCK]" in chunk["text"]
            assert "[DESCRIPTION BLOCK]" in chunk["text"]
            assert "occupazione" in chunk["text"] or "lavoro" in chunk["text"]

    @pytest.mark.asyncio
    async def test_chunk_empty_payload(self):
        from app.ingestion.chunker import chunk_payload

        chunks = await chunk_payload("", "ds1")

        assert chunks == []

    @pytest.mark.asyncio
    async def test_chunk_handles_only_semantic_block(self):
        from app.ingestion.chunker import chunk_payload

        payload = "[SEMANTIC BLOCK] " + "term " * 1000
        dataset_id = "ds1"

        chunks = await chunk_payload(payload, dataset_id)

        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk["dataset_id"] == dataset_id