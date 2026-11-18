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


@pytest.mark.asyncio
async def test_embedding_captures_exact_input_and_request(exporter, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    exp, client = exporter
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"embeddings": [[0.1, 0.2]], "prompt_eval_count": 7}
    with patch("httpx.AsyncClient") as cls:
        http = AsyncMock()
        http.post.return_value = resp
        cls.return_value.__aenter__.return_value = http
        from app.ollama.client import generate_embedding
        await generate_embedding("Testo esatto per l'embedding", model="mxbai-embed-large")
    span = next(s for s in _spans(exp, client) if s.name == "llm.embedding")
    assert _attr(span, "langfuse.observation.input") == "Testo esatto per l'embedding"
    assert _attr(span, "langfuse.observation.model.name") == "mxbai-embed-large"
    assert json.loads(_attr(span, "langfuse.observation.metadata.provider")) == "ollama"
    request = json.loads(_attr(span, "langfuse.observation.metadata.request"))
    assert request["model"] == "mxbai-embed-large"
    assert request["input"] == "Testo esatto per l'embedding"


@pytest.mark.asyncio
async def test_enrichment_captures_exact_rendered_prompt(exporter, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    exp, client = exporter
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"message": {"content": '["occupazione", "lavoro"]'},
                              "prompt_eval_count": 11, "eval_count": 4, "done_reason": "stop"}
    with patch("httpx.AsyncClient") as cls:
        http = AsyncMock()
        http.post.return_value = resp
        cls.return_value.__aenter__.return_value = http
        from app.ingestion.semantic_enricher import enrich
        await enrich("occupazione giovanile")
    spans = _spans(exp, client)
    generation = next(s for s in spans if s.name == "llm.enrichment")
    messages = json.loads(_attr(generation, "langfuse.observation.input"))
    assert messages[0]["role"] == "user"
    assert "occupazione giovanile" in messages[0]["content"]
    span = next(s for s in spans if s.name == "ingestion.semantic_enrichment")
    payload = json.loads(_attr(span, "langfuse.observation.input"))
    assert payload["text"] == "occupazione giovanile"
    assert payload["prompt"] == messages[0]["content"]
    assert json.loads(_attr(generation, "langfuse.observation.metadata.prompt_name")) == "ingestion_semantic_enrichment"


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
         patch.object(service, "generate_batch_embeddings", new=AsyncMock(side_effect=lambda texts: [[0.1] * 4 for _ in texts])):
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


def test_metrics_collector_merges_nested_usage_and_timings():
    with tracing.collect_metrics() as run_metrics:
        with tracing.observe_step("phase.one"):
            pass
        with tracing.collect_metrics() as entity_metrics:
            tracing.record_usage("mistral", "generation", input_tokens=10, output_tokens=5)
            tracing.record_usage("mxbai", "embedding", input_tokens=20)
        entity_summary = tracing.metrics_summary(entity_metrics)
        assert entity_summary["usage"]["total"] == 35
        assert entity_summary["calls"] == {"generation": 1, "embedding": 1}

    summary = tracing.metrics_summary(run_metrics)
    assert summary["usage"] == {"input": 30, "output": 5, "total": 35}
    assert summary["models"]["mistral"]["total"] == 15
    assert summary["models"]["mxbai"]["total"] == 20
    assert "phase.one" in summary["timings_ms"]


def test_otel_endpoint_resolution(monkeypatch):
    from app.observability import otel

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")
    assert otel._signal_endpoint("traces") == "http://collector:4318/v1/traces"
    assert otel._signal_endpoint("metrics") == "http://collector:4318/v1/metrics"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://x/custom")
    assert otel._signal_endpoint("traces") == "http://x/custom"


def test_structlog_processor_adds_trace_context_and_redacts_secrets(monkeypatch):
    from app.observability import otel

    monkeypatch.setenv("OTEL_REDACT_PII", "true")
    event = otel.trace_context_processor(
        None, "info",
        {"authorization": "Bearer secret", "password": "p", "email": "user@example.com",
         "message": "hello", "trace_id": "keep-me"},
    )
    assert event["authorization"] == "[redacted]"
    assert event["password"] == "[redacted]"
    assert event["email"] == "[redacted-email]"
    assert event["trace_id"] == "keep-me"


def test_otel_current_ids_outside_span_are_none():
    from app.observability import otel

    assert otel.current_ids() == (None, None)
