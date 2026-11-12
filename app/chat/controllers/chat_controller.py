import uuid

from fastapi import APIRouter, Header
from app.ollama import client as ollama_client

from app.chat.dto.models import ChatRequest, ChatResponse, ConversationHistory
from app.chat.services.chat_service import generate_answer
from app.common.guards.tenant_guard import resolve_tenant
from app.auth import extract_user_id_from_keycloak_token, require_admin_authorization
from app.conversation import services as conversation_services
from app.observability import tracing

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    x_tenant_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    """
    Chat endpoint with conversation history persistence.
    
    - Extracts user ID from Keycloak JWT
    - Saves user message to MongoDB
    - Generates answer with context from previous messages
    - Saves assistant response to MongoDB
    - Returns answer + sources + conversation ID
    """
    tenant_id = resolve_tenant(x_tenant_id)
    token = require_admin_authorization(authorization)

    # Use provided conversation ID or create new one
    conversation_id = request.conversationId or str(uuid.uuid4())
    user_id = request.userId or str(uuid.uuid4())

    # One Langfuse trace per answer; the conversation is the Langfuse session.
    # A random (generated) user id is not a real user: do not send it.
    with tracing.trace_attributes(
        session_id=conversation_id,
        user_id=request.userId or None,
        tags=["chat", f"tenant:{tenant_id}"],
        metadata={"tenant_id": tenant_id},
        trace_name="chat",
    ), tracing.collect_facts() as facts:
        with tracing.observe_step(
            "chat", as_type="agent",
            input=tracing.io({"message": request.message, "model": request.model}),
        ) as root:
            # generate_answer() already persists both user and assistant messages
            # internally (via append_user_message and _respond), so we must NOT
            # save them here as well — that would duplicate every message.
            response = await generate_answer(
                message=request.message,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                model=request.model,
            )
            tracing.safe_update(root, output=tracing.io({
                "answer": response.answer,
                "sources": [{"title": s.title, "datasetId": s.datasetId, "url": s.url} for s in response.sources],
            }), metadata=dict(facts))
            emit_chat_scores(root, facts)
            response.traceId = root.trace_id

    # Ensure response includes conversation ID
    response.conversationId = conversation_id
    return response


def emit_chat_scores(root, facts: dict) -> None:
    """Automatic, per-trace scores: aggregatable in Langfuse dashboards to study
    retrieval quality and pipeline behaviour statistically."""
    numeric = {
        "retrieval_best_distance": facts.get("best_distance"),
        "retrieval_candidates_kept": facts.get("candidates_kept"),
        "retrieval_threshold_final": facts.get("threshold_final"),
        "answer_sources": facts.get("sources_returned"),
        "context_resources": facts.get("context_resources"),
        "invented_links_removed": facts.get("invented_links"),
    }
    for name, value in numeric.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            tracing.score_trace(root, name, float(value), data_type="NUMERIC")
    booleans = {
        "retrieval_threshold_relaxed": facts.get("threshold_relaxed"),
        "answer_no_result": facts.get("exit_path") == "no_result" if "exit_path" in facts else None,
        "answer_cited_resource": facts.get("cited_resource"),
        "nbs_mode": facts.get("nbs_mode"),
    }
    for name, value in booleans.items():
        if isinstance(value, bool):
            tracing.score_trace(root, name, value)
    for name, key in (("exit_path", "exit_path"), ("language", "language"), ("rerank_method", "rerank_method")):
        if facts.get(key):
            tracing.score_trace(root, name, str(facts[key]), data_type="CATEGORICAL")


@router.get("/models")
async def list_available_models():
    return {"models": await ollama_client.list_models()}


@router.get("/chat/{conversation_id}", response_model=ConversationHistory)
async def get_conversation_history(
    conversation_id: str,
    x_tenant_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    """
    Retrieve full conversation history for a given conversation ID.
    Only the conversation owner can retrieve it (via userId from JWT).
    """
    tenant_id = resolve_tenant(x_tenant_id)
    user_id = require_admin_authorization(authorization)
    
    # Get conversation from MongoDB
    conversation = await conversation_services.get_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    
    if not conversation.messages:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Verify user owns this conversation
    if conversation.userId and conversation.userId != user_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Access denied: conversation belongs to another user")

    messages = [
        {
            "role": msg.role,
            "content": msg.content,
            "createdAt": msg.createdAt.isoformat() if msg.createdAt else None,
        }
        for msg in conversation.messages
    ]
    
    return ConversationHistory(
        conversationId=conversation_id,
        messages=messages,
    )


@router.delete("/chat/{conversation_id}", status_code=200)
async def delete_conversation(
    conversation_id: str,
    x_tenant_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    """
    Delete a conversation and all its messages (GDPR Art. 17 – right to erasure).
    Only the conversation owner can delete it.
    Returns 404 if the conversation does not exist or belongs to another user.
    """
    from fastapi import HTTPException
    tenant_id = resolve_tenant(x_tenant_id)
    user_id = require_admin_authorization(authorization)

    deleted = await conversation_services.delete_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
    )

    if deleted == 0:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found or access denied",
        )

    return {"deleted": deleted, "conversationId": conversation_id}

