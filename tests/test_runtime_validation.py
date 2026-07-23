import asyncio
import json
import math
import os
import statistics
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.chat.services.chat_service import generate_answer
from app.retrieval.vector_search.searcher import vector_search


class _GoldenCollection:
    def __init__(self, records):
        self.records = records

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

        scored.sort(key=lambda item: item[0])
        top = scored[:n_results]

        return {
            "ids": [[item[1]["id"] for item in top]],
            "distances": [[item[0] for item in top]],
            "metadatas": [[item[1]["metadata"] for item in top]],
            "documents": [[item[1]["document"] for item in top]],
        }


def _load_golden_cases():
    data_file = Path(__file__).parent / "data" / "golden_retrieval_cases.json"
    return json.loads(data_file.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _load_golden_cases(), ids=lambda c: c["name"])
def test_golden_retrieval_cases(case):
    collection = _GoldenCollection(case["records"])

    with patch("app.chroma.client.get_tenant_collection", return_value=collection):
        result = vector_search(
            case["tenant_id"],
            case["query_embedding"],
            n_results=5,
        )

    retrieved_ids = [m["dataset_id"] for m in result["metadatas"][0]]
    assert retrieved_ids
    assert retrieved_ids[0] == case["expected_dataset_id"]


@pytest.mark.asyncio
async def test_generate_answer_p95_latency_threshold():
    iterations = int(os.getenv("VALIDATION_PERF_ITERATIONS", "30"))
    p95_threshold_seconds = float(os.getenv("VALIDATION_P95_THRESHOLD_SECONDS", "0.05"))

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["doc1"]],
        "distances": [[0.1]],
        "metadatas": [[
            {
                "tenant_id": "tenant_perf",
                "dataset_id": "ds_perf",
                "title": "Performance dataset",
                "publisher": "TEST",
                "url": "https://example.org/perf",
            }
        ]],
        "documents": [["Dataset per validazione performance"]],
    }

    durations = []
    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 16)):
            with patch("app.ollama.client.generate_completion", new=AsyncMock(return_value="ok")):
                for _ in range(iterations):
                    start = time.perf_counter()
                    await generate_answer(
                        message="query performance",
                        conversation_id=None,
                        tenant_id="tenant_perf",
                    )
                    durations.append(time.perf_counter() - start)

    # statistics.quantiles with n=100 provides percentile cuts; index 94 == P95.
    p95 = statistics.quantiles(durations, n=100)[94]
    assert p95 <= p95_threshold_seconds


@pytest.mark.asyncio
async def test_generate_answer_concurrent_load_smoke():
    concurrency = int(os.getenv("VALIDATION_LOAD_CONCURRENCY", "25"))
    max_total_seconds = float(os.getenv("VALIDATION_LOAD_MAX_TOTAL_SECONDS", "1.5"))

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["doc1"]],
        "distances": [[0.1]],
        "metadatas": [[{"tenant_id": "tenant_load", "dataset_id": "ds_load", "title": "Load"}]],
        "documents": [["load test document"]],
    }

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.2] * 16)):
            with patch("app.ollama.client.generate_completion", new=AsyncMock(return_value="ok")):
                start = time.perf_counter()
                responses = await asyncio.gather(
                    *[
                        generate_answer(
                            message=f"load query {idx}",
                            conversation_id=None,
                            tenant_id="tenant_load",
                        )
                        for idx in range(concurrency)
                    ]
                )
                elapsed = time.perf_counter() - start

    assert len(responses) == concurrency
    assert all(response.answer == "ok" for response in responses)
    assert elapsed <= max_total_seconds