import asyncio

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException


def test_build_prompt_injects_context_and_enforces_no_hallucination():
    from app.chat.services.chat_service import build_prompt

    system, prompt = build_prompt("Show datasets about air quality", "NO2 anomalies detected in Rome. PM10 levels critical.")

    assert "Show datasets about air quality" in prompt
    assert "NO2 anomalies detected in Rome" in prompt
    assert "PM10 levels critical" in prompt
    assert "context" in system.lower()


def test_build_prompt_empty_context_uses_no_result_prompt():
    from app.chat.services.chat_service import build_prompt

    _, prompt = build_prompt("Show datasets about air quality", "")
    assert "Show datasets about air quality" in prompt


def test_build_prompt_includes_previous_conversation_when_available():
    from app.chat.services.chat_service import build_prompt

    _, prompt = build_prompt(
        "And in Milan?",
        "Dataset: Air quality by city",
        "User: Show air quality in Rome\nAssistant: Here are the results",
    )

    assert "Previous conversation:" in prompt
    assert "User: Show air quality in Rome" in prompt
    assert "Question: And in Milan?" in prompt


@pytest.mark.parametrize("message", [
    "Città, mobilità & qualità dell’aria — (2024) {JSON}",
    'Virgolette: "doppie" e \'singole\'',
    "Prima riga\nSeconda riga\t😀",
    "Simboli: [] {} <> / \\ | @ # €",
])
def test_build_prompt_preserves_unicode_and_special_characters(message):
    from app.chat.services.chat_service import build_prompt

    _, prompt = build_prompt(message, "context")
    assert message in prompt


def test_chat_request_normalizes_decomposed_unicode():
    from app.chat.dto.models import ChatRequest

    request = ChatRequest(message="Citta\u0300 e mobilita\u0300")
    assert request.message == "Città e mobilità"


@pytest.mark.parametrize(("message", "language_code"), [
    ("Datos de movilidad", "es"),
    ("Mostrami i dati sul traffico", "it"),
    ("Montrez-moi les données de trafic", "fr"),
    ("Zeig mir Verkehrsdaten", "de"),
])
def test_local_language_detector_handles_clear_queries(message, language_code):
    from app.chat.services.chat_service import _detect_language_locally

    detected_code, _, _ = _detect_language_locally(message)
    assert detected_code == language_code


@pytest.mark.asyncio
async def test_detect_language_uses_llm_for_ambiguous_local_result():
    from app.chat.services.chat_service import _detect_language

    with patch(
        "app.chat.services.chat_service._detect_language_locally",
        return_value=(None, 0.45, 0.01),
    ):
        with patch(
            "app.ollama.client.generate_completion",
            new=AsyncMock(return_value="es"),
        ) as mock_llm:
            assert await _detect_language("Dame datos de tráfico") == "es"

    detector_prompt = mock_llm.await_args.args[0]
    assert "Dame datos de tráfico" in detector_prompt
    assert "ISO 639-1" in detector_prompt


@pytest.mark.asyncio
async def test_detect_language_does_not_call_llm_for_reliable_local_result():
    from app.chat.services.chat_service import _detect_language

    with patch(
        "app.chat.services.chat_service._detect_language_locally",
        return_value=("es", 0.85, 0.70),
    ):
        with patch("app.ollama.client.generate_completion", new=AsyncMock()) as mock_llm:
            assert await _detect_language("Datos sobre movilidad") == "es"

    mock_llm.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["😀", "{} []", "!!!", "@#$%"])
async def test_symbol_only_input_does_not_call_language_llm(message):
    from app.chat.services.chat_service import _detect_language

    with patch("app.ollama.client.generate_completion", new=AsyncMock()) as mock_llm:
        assert await _detect_language(message) is None

    mock_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_language_llm_has_short_timeout():
    from app.chat.services.chat_service import _detect_language

    async def slow_completion(*args, **kwargs):
        await asyncio.sleep(1)

    with patch(
        "app.chat.services.chat_service._detect_language_locally",
        return_value=(None, 0.30, 0.01),
    ):
        with patch("app.chat.services.chat_service.LANGUAGE_DETECTION_TIMEOUT", 0.01):
            with patch("app.ollama.client.generate_completion", side_effect=slow_completion):
                assert await _detect_language("é") is None


@pytest.mark.asyncio
async def test_detect_language_rejects_non_iso_llm_response():
    from app.chat.services.chat_service import _detect_language

    with patch(
        "app.chat.services.chat_service._detect_language_locally",
        return_value=(None, 0.40, 0.02),
    ):
        with patch(
            "app.ollama.client.generate_completion",
            new=AsyncMock(return_value="The language is Spanish."),
        ):
            assert await _detect_language("Dame datos") is None


def test_spanish_prompt_overrides_english_context_language():
    from app.chat.services.chat_service import build_prompt

    system, prompt = build_prompt(
        "Dame datos de tráfico",
        "Title: Road traffic data\nDescription: Traffic counts in European cities",
        lang_code="es",
    )

    assert 'ISO 639-1 code "es"' in system
    assert "exclusively in that language" in system
    assert "Dame datos de tráfico" in prompt


@pytest.mark.asyncio
async def test_determine_n_results_uses_selected_model():
    from app.chat.services.chat_service import _determine_n_results

    with patch(
        "app.ollama.client.generate_completion",
        new=AsyncMock(return_value="12"),
    ) as mock_llm:
        result = await _determine_n_results("Mostrami dati ambientali", model="qwen3.5:4b")

    assert result == 12
    assert mock_llm.await_args.kwargs["model"] == "qwen3.5:4b"


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
            with patch("app.chat.services.chat_service.rerank", return_value=[0, 1]):
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
async def test_generate_answer_no_result_workflow_uses_spanish_prompt():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)) as mock_embed:
            with patch("app.ollama.client.generate_completion", new=AsyncMock(side_effect=["10", "No encontré recursos."])) as mock_llm:
                from app.chat.services.chat_service import generate_answer

                response = await generate_answer(
                    message="Dame datos sobre un tema desconocido",
                    conversation_id=None,
                    tenant_id="tenant_a",
                )

    assert response.answer == "No encontré recursos."
    assert response.sources == []
    assert response.conversationId is not None
    mock_embed.assert_awaited_once()
    assert mock_llm.await_count == 2
    no_result_call = mock_llm.await_args_list[1]
    assert 'ISO 639-1 code "es"' in no_result_call.kwargs["system"]


@pytest.mark.asyncio
async def test_generate_answer_does_not_leak_instructions_when_no_result_llm_fails():
    with patch("app.chat.services.chat_service.embed_query", new=AsyncMock(return_value=[])):
        with patch("app.ollama.client.generate_completion", new=AsyncMock(side_effect=RuntimeError("offline"))):
            from app.chat.services.chat_service import generate_answer

            response = await generate_answer(
                message="¿Qué datos hay sobre tráfico?",
                conversation_id=None,
                tenant_id="tenant_a",
            )

    assert response.answer == "Unable to generate a response at this time."
    assert "You are an assistant" not in response.answer


@pytest.mark.asyncio
async def test_generate_answer_preserves_existing_conversation_id():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

    with patch("app.chroma.client.get_tenant_collection", return_value=mock_collection):
        with patch("app.ollama.client.generate_embedding", new=AsyncMock(return_value=[0.1] * 1024)):
            with patch("app.ollama.client.generate_completion", new=AsyncMock(side_effect=["en", "10", "answer"])):
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
