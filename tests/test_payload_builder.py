import pytest
from unittest.mock import AsyncMock, patch


class TestPayloadBuilder:
    @pytest.mark.asyncio
    async def test_build_combines_semantic_technical_description(self):
        from app.ingestion.payload_builder import build_payload

        dataset = {
            "_id": {"id": "ds1", "type": "Dataset"},
            "title": "Occupazione giovanile",
            "description": "Dataset sull'occupazione giovanile in Italia",
            "publisher": "ISTAT",
            "attrs": {
                "structure": {
                    "value": {
                        "dimensions": [
                            {"id": "FREQ", "label": "Frequenza", "codes": ["A"]},
                            {"id": "GEO", "label": "Geografia", "codes": ["IT"]}
                        ]
                    }
                }
            }
        }

        mock_semantic = ["occupazione", "lavoro", "mercato del lavoro"]
        mock_technical = "FREQ Frequenza GEO Geografia A IT"

        with patch("app.ingestion.payload_builder.enrich", new=AsyncMock(return_value=mock_semantic)):
            with patch("app.ingestion.payload_builder.crawl", new=AsyncMock(return_value=mock_technical)):
                result = await build_payload(dataset)

        assert "[SEMANTIC BLOCK]" in result
        assert "[TECHNICAL BLOCK]" in result
        assert "[DESCRIPTION BLOCK]" in result
        assert "occupazione" in result
        assert "lavoro" in result
        assert "FREQ" in result
        assert "Dataset sull'occupazione" in result

    @pytest.mark.asyncio
    async def test_build_respects_token_limit(self):
        from app.ingestion.payload_builder import build_payload

        dataset = {
            "_id": {"id": "ds1", "type": "Dataset"},
            "title": "Test",
            "description": "x " * 1000,
            "attrs": {"structure": {"value": {"dimensions": [{"id": "DIM" + str(i), "codes": ["C" + str(j) for j in range(20)]} for i in range(50)]}}}
        }

        mock_semantic = ["term" + str(i) for i in range(30)]
        mock_technical = " ".join(["DIM" + str(i) for i in range(50)] + ["C" + str(j) for j in range(1000)])

        with patch("app.ingestion.payload_builder.enrich", new=AsyncMock(return_value=mock_semantic)):
            with patch("app.ingestion.payload_builder.crawl", new=AsyncMock(return_value=mock_technical)):
                result = await build_payload(dataset)

        # Should not exceed ~512 tokens (roughly 2000 chars)
        assert len(result) < 3000

    @pytest.mark.asyncio
    async def test_build_handles_missing_description(self):
        from app.ingestion.payload_builder import build_payload

        dataset = {
            "_id": {"id": "ds1", "type": "Dataset"},
            "title": "Test Dataset",
            "attrs": {}
        }

        with patch("app.ingestion.payload_builder.enrich", new=AsyncMock(return_value=["test"])):
            with patch("app.ingestion.payload_builder.crawl", new=AsyncMock(return_value="")):
                result = await build_payload(dataset)

        assert "[DESCRIPTION BLOCK]" in result
        assert "Test Dataset" in result

    @pytest.mark.asyncio
    async def test_build_handles_missing_title(self):
        from app.ingestion.payload_builder import build_payload

        dataset = {
            "_id": {"id": "ds1", "type": "Dataset"},
            "description": "Only description",
            "attrs": {}
        }

        with patch("app.ingestion.payload_builder.enrich", new=AsyncMock(return_value=["test"])):
            with patch("app.ingestion.payload_builder.crawl", new=AsyncMock(return_value="")):
                result = await build_payload(dataset)

        assert "Only description" in result

    @pytest.mark.asyncio
    async def test_build_includes_dataset_id(self):
        from app.ingestion.payload_builder import build_payload

        dataset = {
            "_id": {"id": "urn:ngsi-ld:Dataset:123", "type": "Dataset"},
            "title": "Test",
            "attrs": {}
        }

        with patch("app.ingestion.payload_builder.enrich", new=AsyncMock(return_value=[])):
            with patch("app.ingestion.payload_builder.crawl", new=AsyncMock(return_value="")):
                result = await build_payload(dataset)

        assert "urn:ngsi-ld:Dataset:123" in result

    @pytest.mark.asyncio
    async def test_build_separator_format(self):
        from app.ingestion.payload_builder import build_payload

        dataset = {"_id": {"id": "ds1"}, "title": "T", "attrs": {}}

        with patch("app.ingestion.payload_builder.enrich", new=AsyncMock(return_value=["a"])):
            with patch("app.ingestion.payload_builder.crawl", new=AsyncMock(return_value="b")):
                result = await build_payload(dataset)

        parts = result.split("[SEP]")
        assert len(parts) == 3