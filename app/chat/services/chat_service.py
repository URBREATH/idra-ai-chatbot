import uuid
import logging

from app.chat.dto.models import ChatResponse, SourceReference
from app.retrieval.embeddings.query_embedder import embed_query
from app.retrieval.vector_search.searcher import vector_search
from app.retrieval.reranker.reranker import rerank
from app.retrieval.context.context_assembler import assemble_context
from app.ollama import client as ollama_client

logger = logging.getLogger(__name__)

TOP_K = 3
NO_RESULT_ANSWER = "No relevant datasets were found for your query."

_SYSTEM_INSTRUCTIONS = (
    "You are a retrieval-augmented assistant for European metadata datasets. "
    "Answer the user's question using ONLY the information contained in the context below. "
    "If the context does not contain the answer, state that no relevant information was found. "
    "Do not use any external knowledge."
)


def build_prompt(message: str, context: str) -> str:
    """Build the RAG prompt with strict context injection (ADR-006: retrieval before generation)."""
    context_block = context if context else "(no context available)"
    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"Context:\n{context_block}\n\n"
        f"Question: {message}\n\n"
        f"Answer:"
    )


async def generate_answer(
    message: str,
    conversation_id: str | None,
    tenant_id: str,
) -> ChatResponse:
    """Orchestrate the retrieval-augmented generation pipeline for a single chat turn.

    Steps follow ARCHITECTURE.md: query embedding -> tenant-isolated vector search ->
    cross-encoder reranking -> top-k context assembly -> LLM generation with
    temperature 0 for determinism. A zero-hallucination no-result workflow is
    applied when retrieval returns no chunks.
    """
    conversation_id = conversation_id or str(uuid.uuid4())

    query_embedding = await embed_query(message)
    if not query_embedding:
        logger.info("Empty query embedding; returning no-result workflow")
        return ChatResponse(answer=NO_RESULT_ANSWER, sources=[], conversationId=conversation_id)

    raw_results = vector_search(tenant_id, query_embedding)
    documents: list[str] = (raw_results.get("documents") or [[]])[0]
    metadatas: list[dict] = (raw_results.get("metadatas") or [[]])[0]
    distances: list[float] = (raw_results.get("distances") or [[]])[0]

    if not documents:
        logger.info("No chunks retrieved for tenant %s; returning no-result workflow", tenant_id)
        return ChatResponse(answer=NO_RESULT_ANSWER, sources=[], conversationId=conversation_id)

    top_indices = rerank(message, documents, metadatas, distances, top_k=TOP_K)
    if not top_indices:
        top_indices = list(range(len(documents)))[:TOP_K]

    top_documents = [documents[i] for i in top_indices]
    top_metadatas = [metadatas[i] for i in top_indices]

    context, sources = assemble_context(top_documents, top_metadatas)

    prompt = build_prompt(message, context)
    answer = await ollama_client.generate_completion(prompt, temperature=0.0)

    return ChatResponse(
        answer=answer,
        sources=sources,
        conversationId=conversation_id,
    )
