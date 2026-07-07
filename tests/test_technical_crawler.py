import pytest
from unittest.mock import AsyncMock, patch


class TestTechnicalCrawler:
    @pytest.mark.asyncio
    async def test_crawl_extracts_sdmx_dimensions(self):
        from app.ingestion.technical_crawler import crawl

        dataset = {
            "_id": {"id": "ds1", "type": "Dataset"},
            "title": "Employment Dataset",
            "attrs": {
                "structure": {
                    "value": {
                        "dimensions": [
                            {"id": "FREQ", "label": "Frequency", "codes": ["A", "M", "Q"]},
                            {"id": "GEO", "label": "Geography", "codes": ["IT", "FR", "DE"]},
                            {"id": "INDICATOR", "label": "Indicator", "codes": ["EMP_RATE", "UNEMP_RATE"]}
                        ]
                    }
                }
            }
        }

        result = await crawl(dataset)

        assert "FREQ" in result
        assert "GEO" in result
        assert "INDICATOR" in result
        assert "EMP_RATE" in result
        assert "IT" in result

    @pytest.mark.asyncio
    async def test_crawl_extracts_nested_descriptions(self):
        from app.ingestion.technical_crawler import crawl

        dataset = {
            "_id": {"id": "ds1", "type": "Dataset"},
            "attrs": {
                "description": {"value": "Dataset sull'occupazione"},
                "dimensions": {
                    "value": {
                        "dimension": [
                            {
                                "id": "FREQ",
                                "label": "Frequenza",
                                "description": {"value": "Frequenza di rilevazione"},
                                "codes": [{"id": "A", "label": "Annuale"}]
                            }
                        ]
                    }
                }
            }
        }

        result = await crawl(dataset)

        assert "Frequenza" in result
        assert "Frequenza di rilevazione" in result
        assert "Annuale" in result

    @pytest.mark.asyncio
    async def test_crawl_handles_dcat_distribution(self):
        from app.ingestion.technical_crawler import crawl

        dataset = {
            "_id": {"id": "ds1", "type": "DistributionDCAT-AP"},
            "attrs": {
                "format": {"value": "CSV"},
                "downloadURL": {"value": "http://example.com/data.csv"},
                "mediaType": {"value": "text/csv"}
            }
        }

        result = await crawl(dataset)

        assert "CSV" in result
        assert "text/csv" in result

    @pytest.mark.asyncio
    async def test_crawl_handles_empty_dataset(self):
        from app.ingestion.technical_crawler import crawl

        dataset = {"_id": {"id": "ds1", "type": "Dataset"}}

        result = await crawl(dataset)

        assert "Dataset" in result
        assert "ds1" in result

    @pytest.mark.asyncio
    async def test_crawl_returns_string_not_list(self):
        from app.ingestion.technical_crawler import crawl

        dataset = {
            "attrs": {
                "structure": {
                    "value": {
                        "dimensions": [{"id": "FREQ", "codes": ["A", "M"]}]
                    }
                }
            }
        }

        result = await crawl(dataset)

        assert isinstance(result, str)
        assert "FREQ" in result
        assert "A" in result

    @pytest.mark.asyncio
    async def test_crawl_recursive_traversal(self):
        from app.ingestion.technical_crawler import crawl

        dataset = {
            "attrs": {
                "catalog": {
                    "value": {
                        "datasets": [
                            {
                                "id": "sub_ds1",
                                "title": "Sub Dataset 1",
                                "structure": {
                                    "value": {"dimensions": [{"id": "SEX", "codes": ["M", "F"]}]}
                                }
                            }
                        ]
                    }
                }
            }
        }

        result = await crawl(dataset)

        assert "SEX" in result
        assert "M" in result
        assert "F" in result

    @pytest.mark.asyncio
    async def test_crawl_deduplicates_terms(self):
        from app.ingestion.technical_crawler import crawl

        dataset = {
            "attrs": {
                "structure": {
                    "value": {
                        "dimensions": [
                            {"id": "GEO", "codes": ["IT", "IT", "FR"]},
                            {"id": "GEO", "codes": ["IT"]}
                        ]
                    }
                }
            }
        }

        result = await crawl(dataset)

        assert result.count("IT") == 1
        assert result.count("GEO") == 1