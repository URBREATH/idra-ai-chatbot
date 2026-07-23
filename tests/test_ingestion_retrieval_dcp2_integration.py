import math
from unittest.mock import AsyncMock, patch

import pytest


class FakeChromaCollection:
    def __init__(self):
        self.records = []

    def upsert(self, ids, embeddings, metadatas, documents):
        for doc_id, emb, meta, doc in zip(ids, embeddings, metadatas, documents):
            self.records.append(
                {
                    "id": doc_id,
                    "embedding": emb,
                    "metadata": meta,
                    "document": doc,
                }
            )

    def delete(self, where):
        dataset_id = where.get("dataset_id") if where else None
        if dataset_id is None:
            return
        self.records = [r for r in self.records if r["metadata"].get("dataset_id") != dataset_id]

    def query(self, query_embeddings, n_results, where):
        query_embedding = query_embeddings[0]

        filtered = []
        for record in self.records:
            metadata = record["metadata"]
            if where and any(metadata.get(k) != v for k, v in where.items()):
                continue
            filtered.append(record)

        scored = []
        for record in filtered:
            distance = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(record["embedding"], query_embedding))
            )
            scored.append((distance, record))

        scored.sort(key=lambda x: x[0])
        top = scored[:n_results]

        return {
            "ids": [[rec["id"] for _, rec in top]],
            "distances": [[dist for dist, _ in top]],
            "metadatas": [[rec["metadata"] for _, rec in top]],
            "documents": [[rec["document"] for _, rec in top]],
        }


async def _fake_embedding(text: str) -> list[float]:
    # Deterministic tiny embedding for stable tests.
    base = float(len(text) % 7)
    return [base, base + 0.1, base + 0.2, base + 0.3, base + 0.4, base + 0.5, base + 0.6, base + 0.7]


@pytest.mark.asyncio
async def test_dcp2_like_ingestion_and_retrieval_flow():
    dataset_id = "urn:ngsi-ld:Dataset:istat:labour:employment-rate-youth"

    dcp2_like_dataset = {
        "_id": {
            "id": dataset_id,
            "type": "https://uri.etsi.org/ngsi-ld/default-context/Dataset",
            "servicePath": "/dcp2/istat",
        },
        "title": "Tasso di occupazione giovanile 15-24 per territorio e frequenza",
        "description": "Serie storica SDMX sul mercato del lavoro giovanile italiano con dettaglio territoriale.",
        "publisher": "ISTAT",
        "keywords": ["occupazione", "giovani", "mercato del lavoro", "sdmx"],
        "attrs": {
            "theme": {"type": "Property", "value": ["populationAndSociety"]},
            "language": {"type": "Property", "value": ["it", "en"]},
            "structure": {
                "type": "Property",
                "value": {
                    "dimensions": [
                        {"id": "FREQ", "label": "Frequenza", "codes": ["A", "Q"]},
                        {"id": "GEO", "label": "Territorio", "codes": ["IT", "ITC4", "ITH5"]},
                        {"id": "AGE", "label": "Classe di eta", "codes": ["Y15-24"]},
                        {"id": "SEX", "label": "Sesso", "codes": ["T", "M", "F"]},
                        {"id": "INDICATOR", "label": "Indicatore", "codes": ["EMP_RATE"]},
                    ],
                    "measures": [{"id": "OBS_VALUE", "unit": "%"}],
                },
            },
            "distribution": {
                "type": "Property",
                "value": [
                    {
                        "id": "urn:ngsi-ld:DistributionDCAT-AP:istat:employment-rate-youth:csv",
                        "format": "text/csv",
                        "accessURL": "https://dati.istat.it/sdmx-json/data/EMP_YOUTH",
                    }
                ],
            },
        },
    }

    fake_collection = FakeChromaCollection()

    with patch("app.ingestion.service.get_datasets_since", new=AsyncMock(return_value=[dcp2_like_dataset])):
        with patch("app.ingestion.service.get_deleted_dataset_ids", new=AsyncMock(return_value=[])):
            with patch("app.ingestion.service.get_all_dataset_ids", new=AsyncMock(return_value=[])):
                with patch("app.ingestion.service.get_tenant_collection", return_value=fake_collection):
                    with patch("app.chroma.client.get_tenant_collection", return_value=fake_collection):
                        with patch("app.ingestion.service.generate_embedding", new=AsyncMock(side_effect=_fake_embedding)):
                            with patch("app.ollama.client.generate_embedding", new=AsyncMock(side_effect=_fake_embedding)):
                                from app.ingestion.service import ingest_tenant
                                from app.retrieval.embeddings.query_embedder import embed_query
                                from app.retrieval.vector_search.searcher import vector_search
                                from app.retrieval.context.context_assembler import assemble_context

                                ingestion_result = await ingest_tenant("tenant_dcp2")

                                assert ingestion_result["total_datasets"] == 1
                                assert ingestion_result["processed"] >= 1
                                assert len(fake_collection.records) >= 1

                                for record in fake_collection.records:
                                    md = record["metadata"]
                                    assert md["tenant_id"] == "tenant_dcp2"
                                    assert md["dataset_id"] == dataset_id
                                    assert md["publisher"] == "ISTAT"

                                query_vector = await embed_query(
                                    "tasso di occupazione giovanile trimestrale in italia"
                                )

                                search_result = vector_search(
                                    "tenant_dcp2",
                                    query_vector,
                                    n_results=5,
                                    where={"dataset_id": dataset_id},
                                )

                                assert search_result["ids"][0]
                                assert all(
                                    m["dataset_id"] == dataset_id
                                    for m in search_result["metadatas"][0]
                                )

                                context, sources = assemble_context(
                                    search_result["documents"][0],
                                    search_result["metadatas"][0],
                                )

                                assert "occupazione" in context.lower()
                                assert len(sources) == 1
                                assert sources[0].datasetId == dataset_id
                                assert sources[0].publisher == "ISTAT"
