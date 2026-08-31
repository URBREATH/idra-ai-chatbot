import os
import uuid
import logging

from dotenv import load_dotenv
from fastapi import HTTPException

from app.chat.dto.models import ChatResponse
from app.retrieval.embeddings.query_embedder import embed_query
from app.retrieval.vector_search.searcher import vector_search
from app.retrieval.reranker.reranker import rerank
from app.retrieval.context.context_assembler import assemble_context
from app.ollama import client as ollama_client
from app.conversation import services as conversation_services
from app.config.config import _SYSTEM_INSTRUCTIONS, _NO_RESULT_INSTRUCTIONS, _RELAXED_NOTICE, DISTANCE_THRESHOLD

logger = logging.getLogger(__name__)

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _h = logging.StreamHandler()          # va su stderr, dove Uvicorn manda i suoi log
    _h.setLevel(logging.DEBUG)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(_h)
    logger.propagate = False

TOP_K = int(os.getenv("TOP_K", 5))

DISTANCE_THRESHOLD = float(os.getenv("DISTANCE_THRESHOLD", "0.55"))
DISTANCE_THRESHOLD_STEP = float(os.getenv("DISTANCE_THRESHOLD_STEP", "0.10"))
DISTANCE_THRESHOLD_MAX = float(os.getenv("DISTANCE_THRESHOLD_MAX", "0.75"))


def _build_no_result_prompt(message: str, conversation_context: str = "") -> str:
    parts = [_NO_RESULT_INSTRUCTIONS]
    if conversation_context:
        parts.append("\nPrevious conversation:")
        parts.append(conversation_context)
    parts.append(f"\nUser's question: {message}")
    parts.append(
        "\nIMPORTANT: If the user's question refers to items already listed in the previous "
        "conversation (words like 'these', 'those', 'the second one'), answer using that "
        "conversation, not a new search. Reply in the user's language."
    )
    parts.append("\nAnswer:")
    return "\n".join(parts)


def build_prompt(
        message: str,
        retrieval_context: str,
        conversation_context: str | None = None,
        relaxed: bool = False,  # <-- NUOVO
) -> str:
    retrieval_block = retrieval_context if retrieval_context else "(no context available)"

    prompt_parts = [_SYSTEM_INSTRUCTIONS]

    if relaxed:  # <-- NUOVO: avviso di ricerca allargata
        prompt_parts.append(_RELAXED_NOTICE)

    if conversation_context:
        prompt_parts.append("Previous conversation:")
        prompt_parts.append(conversation_context)
        prompt_parts.append("")

    prompt_parts.append("Context (from dataset catalog):")
    prompt_parts.append(retrieval_block)
    prompt_parts.append("")

    prompt_parts.append(f"Question: {message}")
    prompt_parts.append("")
    prompt_parts.append("Answer:")

    return "\n".join(prompt_parts)


async def generate_answer(
        message: str,
        conversation_id: str | None,
        tenant_id: str,
        user_id: str | None = None,
        model: str | None = None,
) -> "ChatResponse":
    conversation_id = conversation_id or str(uuid.uuid4())

    if model:
        available = await ollama_client.list_models()
        if model not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model}' not found. Valid models are: {available}",
            )

    conversation_context = ""
    if user_id:
        try:
            conversation_context = await conversation_services.get_context_for_llm(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                limit=10,
            )
        except Exception as e:
            logger.debug(f"Could not load conversation context: {e}")
            conversation_context = ""

    if user_id:
        try:
            await conversation_services.append_user_message(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                message_content=message,
            )
        except Exception as e:
            logger.debug(f"Could not persist user message: {e}")

    async def _respond(answer_text: str, sources_list: list) -> "ChatResponse":
        if user_id:
            try:
                await conversation_services.append_assistant_message(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    message_content=answer_text,
                )
            except Exception as e:
                logger.debug(f"Could not persist assistant message: {e}")
        return ChatResponse(
            answer=answer_text,
            sources=sources_list,
            conversationId=conversation_id,
        )

    async def _no_result() -> "ChatResponse":
        prompt = _build_no_result_prompt(message, conversation_context)
        try:
            if model:
                answer = await ollama_client.generate_completion(prompt, model=model, temperature=0.0)
            else:
                answer = await ollama_client.generate_completion(prompt, temperature=0.0)
        except Exception as e:
            logger.debug(f"No-result generation failed, using fallback: {e}")
            answer = _NO_RESULT_INSTRUCTIONS
        return await _respond(answer, [])

    query_embedding = await embed_query(message)
    if not query_embedding:
        logger.debug("Empty query embedding; returning no-result workflow")
        return await _no_result()

    raw_results = vector_search(tenant_id, query_embedding)
    documents: list[str] = (raw_results.get("documents") or [[]])[0]
    metadatas: list[dict] = (raw_results.get("metadatas") or [[]])[0]
    distances: list[float] = (raw_results.get("distances") or [[]])[0]
    logger.debug("distances for query %r: %s", message, distances)

    if not documents:
        logger.debug("No chunks retrieved for tenant %s; no-result workflow", tenant_id)
        return await _no_result()

    # ------------------------------------------------------------------------
    # Filtro iniziale con la soglia base, poi allargamento a piccoli passi.
    # ------------------------------------------------------------------------
    threshold = DISTANCE_THRESHOLD
    kept = [i for i, d in enumerate(distances) if d <= threshold]

    relaxed = False
    while not kept and threshold < DISTANCE_THRESHOLD_MAX:
        threshold = round(min(threshold + DISTANCE_THRESHOLD_STEP, DISTANCE_THRESHOLD_MAX), 4)
        kept = [i for i, d in enumerate(distances) if d <= threshold]
        if kept:
            relaxed = True
            logger.debug("Nessun risultato sotto la soglia base %.3f; allargata a %.3f -> %d risultati",
                         DISTANCE_THRESHOLD, threshold, len(kept))

    if not kept:
        logger.debug("Nessun risultato entro la soglia massima %.3f; no-result workflow",
                     DISTANCE_THRESHOLD_MAX)
        return await _no_result()

    documents = [documents[i] for i in kept]
    metadatas = [metadatas[i] for i in kept]
    distances = [distances[i] for i in kept]

    top_indices = rerank(message, documents, metadatas, distances, top_k=TOP_K)
    if not top_indices:
        top_indices = list(range(len(documents)))[:TOP_K]

    top_documents = [documents[i] for i in top_indices]
    top_metadatas = [metadatas[i] for i in top_indices]
    context, sources = assemble_context(top_documents, top_metadatas)

    prompt = build_prompt(message, context, conversation_context, relaxed=relaxed)  # <-- passa relaxed

    if model:
        answer = await ollama_client.generate_completion(prompt, model=model, temperature=0.0)
    else:
        answer = await ollama_client.generate_completion(prompt, temperature=0.0)

    return await _respond(answer, sources)