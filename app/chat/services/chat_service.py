import uuid
import logging
from fastapi import HTTPException

from app.chat.dto.models import ChatResponse, SourceReference
from app.retrieval.embeddings.query_embedder import embed_query
from app.retrieval.vector_search.searcher import vector_search
from app.retrieval.reranker.reranker import rerank
from app.retrieval.context.context_assembler import assemble_context
from app.ollama import client as ollama_client
from app.conversation import services as conversation_services

logger = logging.getLogger(__name__)

TOP_K = 5
NO_RESULT_ANSWER = "No relevant datasets were found for your query."

_SYSTEM_INSTRUCTIONS = (
    "You are an assistant for a European open data catalog (dataset metadata: titles, "
    "descriptions, themes, formats, licenses, publishers).\n\n"

    "Rules:\n"
    "- Answer using ONLY the context below. Never invent titles, URLs, publishers, formats, "
    "licenses, or dates. If a detail is not in the context, say it is not available.\n"
    "- If the context has matching datasets, give their concrete details (title, format, "
    "license, link) as found.\n"
    "- If nothing matches, say so clearly and DO NOT guess. Then suggest how to refine the "
    "search: different or broader keywords, a specific theme/location/time, an English term "
    "or synonym, or a format like CSV or GeoJSON. Keep suggestions generic — never name a "
    "specific portal, URL, or dataset unless it is in the context.\n"
    "- You MUST ALWAYS answer in the SAME user's language. Be concise. Do not mention these instructions or the context.\n"
)


def build_prompt(
    message: str,
    retrieval_context: str,
    conversation_context: str | None = None,
) -> str:
    """
    Build the RAG prompt with conversation history + retrieval context injection.
    
    Structure:
    1. System instructions
    2. [Optional] Conversation history (previous messages)
    3. [New] Retrieval context (dataset metadata)
    4. Current question
    
    Args:
        message: Current user message
        retrieval_context: Context from vector search (dataset metadata)
        conversation_context: Optional previous messages formatted as "User: ... / Assistant: ..."
    """
    retrieval_block = retrieval_context if retrieval_context else "(no context available)"
    
    prompt_parts = [_SYSTEM_INSTRUCTIONS]
    
    # Include conversation history if available
    if conversation_context:
        prompt_parts.append("Previous conversation:")
        prompt_parts.append(conversation_context)
        prompt_parts.append("")
    
    # Add retrieval context
    prompt_parts.append("Context (from dataset catalog):")
    prompt_parts.append(retrieval_block)
    prompt_parts.append("")
    
    # Add current question
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
) -> ChatResponse:
    conversation_id = conversation_id or str(uuid.uuid4())

    if model:
        available = await ollama_client.list_models()
        if model not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model}' not found. Valid models are: {available}",
            )

    # 1) Carico la cronologia PREGRESSA (prima di salvare il messaggio corrente,
    #    altrimenti la domanda attuale finirebbe duplicata nel contesto)
    conversation_context = ""
    if user_id:
        try:
            conversation_context = await conversation_services.get_context_for_llm(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                limit=10,
            )
        except Exception as e:
            logger.warning(f"Could not load conversation context: {e}")
            conversation_context = ""

    # 2) Salvo il messaggio dell'utente (DOPO aver letto il contesto pregresso)
    if user_id:
        try:
            await conversation_services.append_user_message(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                message_content=message,
            )
        except Exception as e:
            logger.warning(f"Could not persist user message: {e}")

    # Helper: salva la risposta dell'assistente e costruisce la ChatResponse
    async def _respond(answer_text: str, sources_list: list) -> ChatResponse:
        if user_id:
            try:
                await conversation_services.append_assistant_message(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    message_content=answer_text,
                )
            except Exception as e:
                logger.warning(f"Could not persist assistant message: {e}")
        return ChatResponse(
            answer=answer_text,
            sources=sources_list,
            conversationId=conversation_id,
        )

    query_embedding = await embed_query(message)
    if not query_embedding:
        logger.info("Empty query embedding; returning no-result workflow")
        return await _respond(NO_RESULT_ANSWER, [])

    raw_results = vector_search(tenant_id, query_embedding)
    documents: list[str] = (raw_results.get("documents") or [[]])[0]
    metadatas: list[dict] = (raw_results.get("metadatas") or [[]])[0]
    distances: list[float] = (raw_results.get("distances") or [[]])[0]

    if not documents:
        logger.info("No chunks retrieved for tenant %s; no-result workflow", tenant_id)
        return await _respond(NO_RESULT_ANSWER, [])

    top_indices = rerank(message, documents, metadatas, distances, top_k=TOP_K)
    if not top_indices:
        top_indices = list(range(len(documents)))[:TOP_K]

    top_documents = [documents[i] for i in top_indices]
    top_metadatas = [metadatas[i] for i in top_indices]
    context, sources = assemble_context(top_documents, top_metadatas)

    prompt = build_prompt(message, context, conversation_context)

    if model:
        answer = await ollama_client.generate_completion(prompt, model=model, temperature=0.0)
    else:
        answer = await ollama_client.generate_completion(prompt, temperature=0.0)

    return await _respond(answer, sources)
