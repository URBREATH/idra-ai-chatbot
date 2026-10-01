import os
import re
import uuid
import logging

from dotenv import load_dotenv
from fastapi import HTTPException

from app.chat.dto.models import ChatResponse
from app.retrieval.embeddings.query_embedder import embed_query
from app.retrieval.vector_search.searcher import vector_search, DEFAULT_N_RESULTS
from app.retrieval.reranker.reranker import rerank
from app.retrieval.context.context_assembler import assemble_context
from app.ollama import client as ollama_client
from app.conversation import services as conversation_services
from app.config.config import _SYSTEM_INSTRUCTIONS, _NO_RESULT_INSTRUCTIONS, _RELAXED_NOTICE

logger = logging.getLogger(__name__)

load_dotenv()

logging.getLogger("app").setLevel(logging.DEBUG)  # <-- adatta 'app' al package radice
if not logging.getLogger().handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(_h)
logger = logging.getLogger(__name__)

TOP_K = int(os.getenv("TOP_K", -1))
DISTANCE_THRESHOLD = float(os.getenv("DISTANCE_THRESHOLD", "0.55"))
DISTANCE_THRESHOLD_STEP = float(os.getenv("DISTANCE_THRESHOLD_STEP", "0.10"))
DISTANCE_THRESHOLD_MAX = float(os.getenv("DISTANCE_THRESHOLD_MAX", "0.75"))
LOG_TOP_FOUND = int(os.getenv("LOG_TOP_FOUND", 100))
MAX_N_RESULTS = int(os.getenv("MAX_N_RESULTS", 100))

_N_RESULTS_ANALYSIS_PROMPT = (
    "You are a query analyser. Given the user query below, estimate how many "
    "search results should be retrieved from the database. "
    "Return ONLY a single integer, nothing else.\n"
    "- If the query is specific/narrow (e.g. a single topic, a name, a date), return a low number (1-15).\n"
    "- If the query is broad (e.g. a theme, a category), return a medium number (16-50).\n"
    "- If the query asks for ALL, every, complete list, catalogue, or comprehensive results, "
    f"return a high number (51-{MAX_N_RESULTS}).\n"
    "\n"
    "Query: \"{message}\"\n"
    "Integer:"
)


async def _determine_n_results(message: str) -> int:
    """Use the LLM to estimate the appropriate number of search results for the query."""
    try:
        prompt = _N_RESULTS_ANALYSIS_PROMPT.format(message=message)
        raw = await ollama_client.generate_completion(prompt, temperature=0.0)
        number = int(raw.strip())
        clamped = max(1, min(number, MAX_N_RESULTS))
        logger.debug("LLM determined n_results=%d (raw=%r, clamped to [1, %d])", clamped, raw.strip(), MAX_N_RESULTS)
        return clamped
    except Exception as e:
        logger.debug("Could not determine n_results via LLM (%s), falling back to DEFAULT_N_RESULTS=%d", e, DEFAULT_N_RESULTS)
        return DEFAULT_N_RESULTS


_LANGUAGE_DETECTION_PROMPT = (
    "Identify the language of the user message below. Return ONLY its lowercase "
    "ISO 639-1 two-letter code, with no punctuation or explanation. Detect the "
    "language from the message itself, not from the topic or named entities.\n\n"
    "User message:\n<message>{message}</message>\n\nLanguage code:"
)


async def _detect_language(text: str, model: str | None = None) -> str | None:
    """Ask the LLM for the message language as an ISO 639-1 code."""
    try:
        kwargs = {"temperature": 0.0}
        if model:
            kwargs["model"] = model
        raw = await ollama_client.generate_completion(
            _LANGUAGE_DETECTION_PROMPT.format(message=text),
            **kwargs,
        )
        code = raw.strip().lower()
        if re.fullmatch(r"[a-z]{2}", code):
            return code
        logger.debug("Language detector returned an invalid code: %r", raw)
    except Exception as e:
        logger.debug("Could not detect query language via LLM: %s", e)
    return None


def _language_directive(lang_code: str | None) -> str:
    if not lang_code:
        return ""
    return (
        f'The user message language was identified as ISO 639-1 code "{lang_code}". '
        "You MUST write the entire answer exclusively in that language. Ignore the "
        "language of the context and conversation history.\n\n"
    )


def _log_found_resources(documents, metadatas, distances) -> None:
    n_show = min(MAX_N_RESULTS, len(documents))
    logger.debug("Prime %d risorse trovate (soglia base=%.3f, tetto=%.3f):",
                 n_show, DISTANCE_THRESHOLD, DISTANCE_THRESHOLD_MAX)
    for rank in range(n_show):
        meta = metadatas[rank] or {}
        dist = distances[rank]
        label = meta.get("title") or meta.get("dataset_id") or "(senza titolo)"
        entro = "OK " if dist <= DISTANCE_THRESHOLD else "  -"
        logger.debug("  #%2d  dist=%.4f  [%s]  %s", rank + 1, dist, entro, label)


def _build_no_result_prompt(message: str, conversation_context: str = "", lang_code: str | None = None) -> "tuple[str, str]":
    system = _language_directive(lang_code) + _NO_RESULT_INSTRUCTIONS
    user_parts: list[str] = []
    if conversation_context:
        user_parts.append("Previous conversation:")
        user_parts.append(conversation_context)
    user_parts.append(f"User's question: {message}")
    user_parts.append(
        "IMPORTANT: If the user's question refers to items already listed in the previous "
        "conversation (words like 'these', 'those', 'the second one'), answer using that "
        "conversation, not a new search."
    )
    return system, "\n".join(user_parts)


def build_prompt(message, retrieval_context, conversation_context=None, relaxed=False, lang_code: str | None = None) -> "tuple[str, str]":
    system_parts: list[str] = [_language_directive(lang_code), _SYSTEM_INSTRUCTIONS]
    if relaxed:
        system_parts.append(_RELAXED_NOTICE)
    system = "\n".join(system_parts)

    user_parts: list[str] = []
    if conversation_context:
        user_parts.append("Previous conversation:")
        user_parts.append(conversation_context)
        user_parts.append("")
    user_parts.append("Context (metadata of the retrieved resources):")
    user_parts.append(retrieval_context if retrieval_context else "(no context available)")
    user_parts.append("")
    user_parts.append(f"Question: {message}")
    user_parts.append("")
    return system, "\n".join(user_parts)


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
                conversation_id=conversation_id, tenant_id=tenant_id, limit=20,
            )
        except Exception as e:
            logger.debug(f"Could not load conversation context: {e}")
            conversation_context = ""

    lang_code = await _detect_language(message, model=model)
    logger.debug("Detected language for query: %s", lang_code)

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
        system, user_prompt = _build_no_result_prompt(message, conversation_context, lang_code=lang_code)
        try:
            if model:
                answer = await ollama_client.generate_completion(user_prompt, model=model, temperature=0.0, system=system)
            else:
                answer = await ollama_client.generate_completion(user_prompt, temperature=0.0, system=system)
        except Exception as e:
            logger.debug(f"No-result generation failed, using fallback: {e}")
            answer = "Unable to generate a response at this time."
        return await _respond(answer, [])

    query_embedding = await embed_query(message)
    if not query_embedding:
        logger.debug("Empty query embedding; no-result workflow")
        return await _no_result()

    n_results = await _determine_n_results(message)
    raw_results = vector_search(tenant_id, query_embedding, n_results=n_results)
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

    # NB: assemble_context deve includere i metadati (title, description, format,
    # license, url), perche' il documento vettorizzato ora e' solo semantico.
    context, sources = assemble_context(top_documents, top_metadatas)

    system, user_prompt = build_prompt(message, context, conversation_context, relaxed=relaxed, lang_code=lang_code)

    if model:
        answer = await ollama_client.generate_completion(user_prompt, model=model, temperature=0.0, system=system)
    else:
        answer = await ollama_client.generate_completion(user_prompt, temperature=0.0, system=system)

    return await _respond(answer, sources)
