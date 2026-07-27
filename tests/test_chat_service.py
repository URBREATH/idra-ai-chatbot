import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException


def test_build_prompt_injects_context_and_enforces_no_hallucination():
    from app.chat.services.chat_service import build_prompt

    prompt = build_prompt("Show datasets about air quality", "NO2 anomalies detected in Rome. PM10 levels critical.")

    assert "Show datasets about air quality" in prompt
    assert "NO2 anomalies detected in Rome" in prompt
    assert "PM10 levels critical" in prompt
    assert "context" in prompt.lower() or "contesto" in prompt.lower()


def test_build_prompt_empty_context_uses_no_result_prompt():
    from app.chat.services.chat_service import build_prompt

    prompt = build_prompt("Show datasets about air quality", "")
    assert "Show datasets about air quality" in prompt


def test_build_prompt_includes_previous_conversation_when_available():
    from app.chat.services.chat_service import build_prompt

    prompt = build_prompt(
        "And in Milan?",
        "Dataset: Air quality by city",
        "User: Show air quality in Rome\nAssistant: Here are the results",
    )

    assert "Previous conversation:" in prompt
    assert "User: Show air quality in Rome" in prompt
    assert "Question: And in Milan?" in prompt


@pytest.mark.asyncio
async def test_generate_answer_returns_response_with_sources_and_conversation_id():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["doc1", "doc2"]],
        "distances": [[0.1, 0.2]],
        "metadatas": [[
            {"tenant_id": "tenant_a", "dataset_id": "ds1", "title": "NO2 Air Quality", "publisher": "BEOPEN", "url": "https://a.com"},
            {"tenant_id": "tenant_a", "dataset_id": "ds2", "title": "PM10 Air Quality", "publisher": "EEA", "url": "https://b.com"},
        ]],
        "documents": [["no2 anomalies in rome", "pm10 levels critical"]],
    }

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ollama.client.generate_completion", new=AsyncMock(return_value="Based on the datasets, air quality shows anomalies.")):
                from app.chat.services.chat_service import generate_answer

                response = await generate_answer(
                    message="Show datasets about air quality",
                    conversation_id=None,
                    tenant_id="tenant_a",
                )

    assert response.answer == "Based on the datasets, air quality shows anomalies."
    assert response.conversationId is not None
    assert len(response.sources) == 2
    assert response.sources[0].title == "NO2 Air Quality"
    assert response.sources[0].datasetId == "ds1"
    assert response.sources[1].datasetId == "ds2"


@pytest.mark.asyncio
async def test_generate_answer_no_result_workflow_returns_fallback_without_llm():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)) as mock_embed:
            with patch("app.ollama.client.generate_completion", new=AsyncMock(return_value="SHOULD NOT BE CALLED")) as mock_llm:
                from app.chat.services.chat_service import generate_answer

                response = await generate_answer(
                    message="xyz unknown topic",
                    conversation_id=None,
                    tenant_id="tenant_a",
                )

    assert response.answer != "SHOULD NOT BE CALLED"
    assert response.sources == []
    assert response.conversationId is not None
    mock_embed.assert_awaited_once()
    mock_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_answer_preserves_existing_conversation_id():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            from app.chat.services.chat_service import generate_answer

            response = await generate_answer(
                message="anything",
                conversation_id="existing-uuid-123",
                tenant_id="tenant_a",
            )

    assert response.conversationId == "existing-uuid-123"


@pytest.mark.asyncio
async def test_generate_answer_uses_temperature_zero_for_determinism():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["doc1"]],
        "distances": [[0.1]],
        "metadatas": [[{"tenant_id": "tenant_a", "dataset_id": "ds1", "title": "T"}]],
        "documents": [["some text"]],
    }

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ollama.client.generate_completion", new=AsyncMock(return_value="answer")) as mock_llm:
                from app.chat.services.chat_service import generate_answer

                await generate_answer(message="q", conversation_id=None, tenant_id="tenant_a")

    call_kwargs = mock_llm.call_args.kwargs
    assert call_kwargs.get("temperature") == 0.0


@pytest.mark.asyncio
async def test_generate_answer_injects_conversation_context_in_prompt():
    with patch("app.chat.services.chat_service.conversation_services.get_context_for_llm", new=AsyncMock(return_value="User: hello\nAssistant: hi")):
        with patch("app.chat.services.chat_service.embed_query", new=AsyncMock(return_value=[0.2] * 4)):
            with patch("app.chat.services.chat_service.vector_search", return_value={
                "documents": [["dataset chunk"]],
                "metadatas": [[{"dataset_id": "ds1", "title": "Dataset 1", "publisher": "EU", "url": "https://example.org"}]],
                "distances": [[0.1]],
            }):
                with patch("app.chat.services.chat_service.rerank", return_value=[0]):
                    with patch("app.chat.services.chat_service.assemble_context", return_value=("Dataset 1 context", [])):
                        with patch("app.ollama.client.generate_completion", new=AsyncMock(return_value="ok")) as mock_llm:
                            from app.chat.services.chat_service import generate_answer

                            await generate_answer(
                                message="next question",
                                conversation_id="conv-1",
                                tenant_id="tenant-a",
                                user_id="user-1",
                            )

    prompt_arg = mock_llm.await_args.args[0]
    assert "Previous conversation:" in prompt_arg
    assert "User: hello" in prompt_arg


@pytest.mark.asyncio
async def test_generate_answer_raises_400_for_unknown_model():
    with patch("app.ollama.client.list_models", new=AsyncMock(return_value=["llama3", "mistral"])):
        from app.chat.services.chat_service import generate_answer

        with pytest.raises(HTTPException) as exc:
            await generate_answer(
                message="hello",
                conversation_id="conv-1",
                tenant_id="tenant-a",
                model="unknown-model",
            )

    assert exc.value.status_code == 400
    assert "not found" in str(exc.value.detail)
