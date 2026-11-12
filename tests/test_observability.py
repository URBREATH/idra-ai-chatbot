"""Observability tests: real Langfuse SDK + in-memory OpenTelemetry exporter
(no Langfuse server needed). Verifies which spans the pipeline emits."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability import tracing


@pytest.fixture(scope="module")
def _langfuse():
    # Langfuse keeps one tracer provider per public key: build it once per module.
    from langfuse import Langfuse

    exp = InMemorySpanExporter()
    client = Langfuse(public_key="pk-lf-test", secret_key="sk-lf-test", base_url="http://localhost:1",
                      span_exporter=exp, flush_at=1, flush_interval=0.1)
    yield exp, client


@pytest.fixture
def exporter(_langfuse):
    exp, client = _langfuse
    client.flush()
    exp.clear()
    client.create_score = MagicMock()          # scores go through the REST API: capture them
    tracing._client, tracing._init_done = client, True
    yield exp, client
    client.flush()
    tracing.reset_for_tests()


def _spans(exp, client):
    client.flush()
    return exp.get_finished_spans()


def _attr(span, key):
    return (span.attributes or {}).get(key)


def test_disabled_tracing_is_noop():
    tracing.reset_for_tests()
    with patch.dict("os.environ", {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""}):
        assert tracing.get_client() is None
        with tracing.observe_step("x") as obs:
            obs.update(output="ignored")
        assert obs is tracing.NOOP
        assert tracing.create_score("s", True, trace_id="t") is False
    tracing.reset_for_tests()


def test_observe_step_records_errors(exporter):
    exp, client = exporter
    with pytest.raises(ValueError):
        with tracing.observe_step("boom"):
            raise ValueError("bad")
    span = next(s for s in _spans(exp, client) if s.name == "boom")
    assert _attr(span, "langfuse.observation.level") == "ERROR"


@pytest.mark.asyncio
async def test_generation_records_model_usage_and_timings(exporter):
    exp, client = exporter
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"message": {"content": "ciao"}, "prompt_eval_count": 120, "eval_count": 30,
                              "eval_duration": 1_500_000_000, "total_duration": 2_000_000_000,
                              "done_reason": "stop"}
    with patch("httpx.AsyncClient") as cls:
        http = AsyncMock()
        http.post.return_value = resp
        cls.return_value.__aenter__.return_value = http
        from app.ollama.client import generate_completion
        out = await generate_completion("hello", model="llama3.1", name="llm.answer")
    assert out == "ciao"
    span = next(s for s in _spans(exp, client) if s.name == "llm.answer")
    assert _attr(span, "langfuse.observation.type") == "generation"
    assert _attr(span, "langfuse.observation.model.name") == "llama3.1"
    usage = json.loads(_attr(span, "langfuse.observation.usage_details"))
    assert usage == {"input": 120, "output": 30, "total": 150}
    assert _attr(span, "langfuse.observation.metadata.tokens_per_second") is not None


def test_chat_endpoint_emits_pipeline_trace(exporter):
    exp, client = exporter
    from fastapi.testclient import TestClient
    from app.main import app

    results = {
        "documents": [["Air quality NO2 dataset", "Noise map"]],
        "metadatas": [[{"tenant_id": "default-tenant", "dataset_id": "ds1", "title": "Air quality",
                        "url": "http://x/ds1", "entity_type": "Dataset"},
                       {"tenant_id": "default-tenant", "dataset_id": "ds2", "title": "Noise",
                        "entity_type": "Dataset"}]],
        "distances": [[0.2, 0.9]],
    }
    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()), \
         patch("app.main.get_database") as db, \
         patch("app.chat.services.chat_service.conversation_services.get_context_for_llm", new=AsyncMock(return_value="")), \
         patch("app.chat.services.chat_service.conversation_services.append_user_message", new=AsyncMock()), \
         patch("app.chat.services.chat_service.conversation_services.append_assistant_message", new=AsyncMock()), \
         patch("app.chat.services.chat_service.embed_query", new=AsyncMock(return_value=[0.1] * 4)), \
         patch("app.chat.services.chat_service.vector_search", return_value=results), \
         patch("app.retrieval.reranker.reranker.get_cross_encoder", return_value=None), \
         patch("app.ollama.client.generate_completion",
               new=AsyncMock(return_value="1. Air quality - NO2 data. http://x/ds1")), \
         patch("app.chat.controllers.chat_controller.require_admin_authorization", return_value="t"):
        db.return_value.__getitem__.return_value.create_index = AsyncMock()
        with TestClient(app) as http:
            r = http.post("/chat", json={"message": "datasets about air quality in Paris",
                                         "conversationId": "conv-1"},
                          headers={"Authorization": "Bearer t"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["traceId"]

    spans = _spans(exp, client)
    names = {s.name for s in spans}
    for expected in ("chat", "chat.load_history", "chat.language_detection", "retrieval.search",
                     "retrieval.rerank", "chat.context_assembly", "chat.guardrails"):
        assert expected in names, f"missing span {expected}: {names}"
    # one trace, grouped by conversation (session)
    trace_ids = {format(s.context.trace_id, "032x") for s in spans if s.name.startswith(("chat", "retrieval"))}
    assert trace_ids == {body["traceId"]}
    root = next(s for s in spans if s.name == "chat")
    assert _attr(root, "session.id") == "conv-1"
    assert json.loads(_attr(root, "langfuse.observation.metadata.exit_path")) == "normal"
    retrieval = next(s for s in spans if s.name == "retrieval.search")
    assert _attr(retrieval, "langfuse.observation.type") == "retriever"
    assert json.loads(_attr(retrieval, "langfuse.observation.metadata.kept")) == 1

    score_names = {c.kwargs["name"] for c in client.create_score.call_args_list}
    assert {"retrieval_best_distance", "exit_path", "language", "rerank_method"} <= score_names


def test_feedback_creates_langfuse_score(exporter):
    exp, client = exporter
    from fastapi.testclient import TestClient
    from app.main import app

    with patch("app.main.conversation_repositories.initialize_conversation_indexes", new=AsyncMock()), \
         patch("app.main.get_database") as db:
        db.return_value.__getitem__.return_value.insert_one = AsyncMock()
        db.return_value.__getitem__.return_value.create_index = AsyncMock()
        with TestClient(app) as http:
            r = http.post("/chat/feedback", json={"conversationId": "conv-1", "traceId": "a" * 32,
                                                  "rating": "negative", "comment": "wrong link"})
            bad = http.post("/chat/feedback", json={"conversationId": "conv-1", "rating": "meh"})
    assert r.status_code == 200 and r.json()["langfuse"] is True
    assert bad.status_code == 422
    kwargs = client.create_score.call_args.kwargs
    assert kwargs["name"] == "user_feedback" and kwargs["value"] == 0.0
    assert kwargs["trace_id"] == "a" * 32 and kwargs["data_type"] == "BOOLEAN"


@pytest.mark.asyncio
async def test_ingestion_emits_run_and_entity_traces(exporter):
    exp, client = exporter
    from app.ingestion import service

    entities = [{"_id": {"id": "ds1", "type": "Dataset"}, "source": "idra-mysql",
                 "attrs": {"title": {"value": "Trees"}, "description": {"value": "Urban trees"}}}]
    collection = MagicMock()
    collection.count.return_value = 0
    with patch.object(service, "get_indexed_hashes", return_value={}), \
         patch.object(service, "get_tenant_collection", return_value=collection), \
         patch.object(service, "get_datasets_since", new=AsyncMock(return_value=entities)), \
         patch.object(service, "get_deleted_dataset_ids", new=AsyncMock(return_value=[])), \
         patch.object(service, "get_all_dataset_ids", new=AsyncMock(return_value=["ds1"])), \
         patch.object(service, "build_payload", new=AsyncMock(return_value="Trees urban")), \
         patch.object(service, "generate_embedding", new=AsyncMock(return_value=[0.1] * 4)):
        result = await service.ingest_tenant("t")
    assert result["total_datasets"] == 1

    spans = _spans(exp, client)
    names = [s.name for s in spans]
    for expected in ("ingestion.run", "ingestion.load_sources", "ingestion.plan",
                     "ingestion.entity", "ingestion.build_payload", "ingestion.chroma_upsert"):
        assert expected in names, f"missing span {expected}: {names}"
    run = next(s for s in spans if s.name == "ingestion.run")
    entity = next(s for s in spans if s.name == "ingestion.entity")
    upsert = next(s for s in spans if s.name == "ingestion.chroma_upsert")
    assert entity.context.trace_id != run.context.trace_id      # one trace per entity
    assert upsert.context.trace_id == run.context.trace_id      # phases belong to the run trace
    assert _attr(entity, "session.id") == _attr(run, "session.id")
    assert json.loads(_attr(run, "langfuse.observation.output"))["total_datasets"] == 1
