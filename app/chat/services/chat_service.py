import os
import uuid
import logging

from dotenv import load_dotenv
from fastapi import HTTPException

from app.chat.dto.models import ChatResponse
from app.chat.services.chat_followup import is_followup, rewrite_query
from app.retrieval.embeddings.query_embedder import embed_query
from app.retrieval.vector_search.searcher import vector_search
from app.retrieval.reranker.reranker import rerank
from app.retrieval.context.context_assembler import assemble_context
from app.ollama import client as ollama_client
from app.conversation import services as conversation_services
from app.config.config import SYSTEM_INSTRUCTIONS, NO_RESULT_INSTRUCTIONS, RELAXED_NOTICE, _NBS_INTENT, NBS_INSTRUCTIONS

logger = logging.getLogger(__name__)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,          # <-- rimuove gli handler esistenti e reimposta i tuoi
)
logging.getLogger("app").setLevel(logging.DEBUG)   # i tuoi moduli restano a DEBUG
logger = logging.getLogger(__name__)

TOP_K = int(os.getenv("TOP_K", 10))
DISTANCE_THRESHOLD = float(os.getenv("DISTANCE_THRESHOLD", "0.55"))
DISTANCE_THRESHOLD_STEP = float(os.getenv("DISTANCE_THRESHOLD_STEP", "0.10"))
DISTANCE_THRESHOLD_MAX = float(os.getenv("DISTANCE_THRESHOLD_MAX", "0.75"))
LOG_TOP_FOUND = int(os.getenv("LOG_TOP_FOUND", 10))


def _log_found_resources(documents, metadatas, distances) -> None:
    n_show = min(LOG_TOP_FOUND, len(documents))
    logger.debug("Prime %d risorse trovate (soglia base=%.3f, tetto=%.3f):",
                 n_show, DISTANCE_THRESHOLD, DISTANCE_THRESHOLD_MAX)
    for rank in range(n_show):
        meta = metadatas[rank] or {}
        dist = distances[rank]
        label = meta.get("title") or meta.get("dataset_id") or "(senza titolo)"
        entro = "OK " if dist <= DISTANCE_THRESHOLD else "  -"
        logger.debug("  #%2d  dist=%.4f  [%s]  %s", rank + 1, dist, entro, label)

def is_nbs_question(message: str) -> bool:
    """True if the question asks how to SOLVE a problem (NBS mode), not just to list data."""
    m = str(message or "").lower()
    return any(w in m for w in _NBS_INTENT)

def _build_no_result_prompt(message: str, conversation_context: str = "") -> str:
    parts = [NO_RESULT_INSTRUCTIONS]
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


def build_prompt(message, retrieval_context, conversation_context=None,
                 relaxed=False, system=SYSTEM_INSTRUCTIONS) -> str:      # <-- system scelto dall'esterno
    retrieval_block = retrieval_context if retrieval_context else "(no context available)"
    prompt_parts = [system]
    if relaxed:
        prompt_parts.append(RELAXED_NOTICE)
    if conversation_context:
        prompt_parts.append("Previous conversation:")
        prompt_parts.append(conversation_context)
        prompt_parts.append("")
    prompt_parts.append("Context (metadata of the retrieved resources):")
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
    logger.debug("MEMORIA - conversation_id=%s | user_id=%s", conversation_id, user_id)

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
                conversation_id=conversation_id, user_id=user_id,tenant_id=tenant_id, limit=10,
            )
        except Exception as e:
            logger.debug(f"Could not load conversation context: {e}")
            conversation_context = ""

    if user_id:
        try:
            await conversation_services.append_user_message(
                conversation_id=conversation_id, tenant_id=tenant_id,
                user_id=user_id, message_content=message,
            )
        except Exception as e:
            logger.debug(f"Could not persist user message: {e}")

    async def _respond(answer_text: str, sources_list: list) -> "ChatResponse":
        if user_id:
            try:
                await conversation_services.append_assistant_message(
                    conversation_id=conversation_id, tenant_id=tenant_id,
                    user_id=user_id, message_content=answer_text,
                )
            except Exception as e:
                logger.debug(f"Could not persist assistant message: {e}")
        return ChatResponse(answer=answer_text, sources=sources_list, conversationId=conversation_id)

    async def _no_result() -> "ChatResponse":
        prompt = _build_no_result_prompt(message, conversation_context)
        try:
            if model:
                answer = await ollama_client.generate_completion(prompt, model=model, temperature=0.0)
            else:
                answer = await ollama_client.generate_completion(prompt, temperature=0.0)
        except Exception as e:
            logger.debug(f"No-result generation failed, using fallback: {e}")
            answer = NO_RESULT_INSTRUCTIONS
        return await _respond(answer, [])

    search_text = message
    if conversation_context and is_followup(message):
        search_text = await rewrite_query(message, conversation_context, model=model)

    nbs = is_nbs_question(message) or is_nbs_question(search_text)  # <-- fix
    logger.debug("NBS intent: message=%s search=%s -> %s",
                 is_nbs_question(message), is_nbs_question(search_text), nbs)

    query_embedding = await embed_query(search_text)
    if not query_embedding:
        logger.debug("Empty query embedding; no-result workflow")
        return await _no_result()

    where = {"is_nbs": True} if nbs else None
    logger.debug("WHERE passato alla ricerca: %s", where)
    raw_results = vector_search(tenant_id, query_embedding, where=where)
    documents = (raw_results.get("documents") or [[]])[0]
    metadatas = (raw_results.get("metadatas") or [[]])[0]
    distances = (raw_results.get("distances") or [[]])[0]

    logger.debug("distances for query %r: %s", message, distances)
    if documents:
        _log_found_resources(documents, metadatas, distances)

    if not documents:
        logger.debug("Nessun candidato per tenant %s; no-result workflow", tenant_id)
        return await _no_result()

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
        logger.debug("Nessun risultato entro la soglia massima %.3f; no-result", DISTANCE_THRESHOLD_MAX)
        return await _no_result()

    documents = [documents[i] for i in kept]
    metadatas = [metadatas[i] for i in kept]
    distances = [distances[i] for i in kept]

    top_indices = rerank(message, documents, metadatas, distances, top_k=TOP_K)
    if not top_indices:
        top_indices = list(range(len(documents)))[:TOP_K]

    top_documents = [documents[i] for i in top_indices]
    top_metadatas = [metadatas[i] for i in top_indices]

    logger.debug("Risorse passate all'LLM (dopo soglia e rerank): %s",
                 [(m or {}).get("title") or (m or {}).get("dataset_id") for m in top_metadatas])

    context, sources = assemble_context(top_documents, top_metadatas)
    logger.debug("CONTEXT PASSATO AL MODELLO:\n%s", context[:2000])

    system = NBS_INSTRUCTIONS if nbs else SYSTEM_INSTRUCTIONS
    logger.debug("PROMPT SCELTO: %s", "NBS" if nbs else "GENERIC")
    prompt = build_prompt(message, context, conversation_context, relaxed=relaxed, system=system)

    if model:
        answer = await ollama_client.generate_completion(prompt, model=model, temperature=0.0)
    else:
        answer = await ollama_client.generate_completion(prompt, temperature=0.0)

    return await _respond(answer, sources)
