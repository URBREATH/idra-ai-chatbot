import os
from typing import Any

from dotenv import load_dotenv

from app.common.utils.reranker_encoder import get_cross_encoder, OLLAMA_RERANKER_MODEL
from app.observability import otel, tracing

load_dotenv()
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", 10))


def _distance_based_rank(distances: list[float], top_k: int = DEFAULT_TOP_K) -> list[int]:
    """Fallback ranking using ChromaDB cosine distances (lower distance = more similar)."""
    if not distances:
        return []
    ranked = sorted(range(len(distances)), key=lambda i: distances[i])
    return ranked[:top_k]


def _cross_encoder_scores(query: str, documents: list[str]) -> list[float] | None:
    encoder = get_cross_encoder()
    if encoder is None or not documents:
        return None
    return [float(s) for s in encoder.predict([(query, doc) for doc in documents])]


def _cross_encoder_rank(
    query: str,
    documents: list[str],
    top_k: int = DEFAULT_TOP_K,
) -> list[int]:
    """Rank documents using ms-marco-MiniLM-L-6-v2 cross-encoder (ADR-007)."""
    scores = _cross_encoder_scores(query, documents)
    if not scores:
        return []
    ranked = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)
    return ranked[:top_k]


def rerank(
    query: str,
    documents: list[str],
    metadatas: list[dict[str, Any]],
    distances: list[float],
    top_k: int = DEFAULT_TOP_K,
) -> list[int]:
    """Rerank retrieved chunks and return the indices of the top-k most relevant.

    Uses the cross-encoder when available; otherwise falls back to distance-based
    ordering so the pipeline remains functional on CPU-only deployments without
    the extra model downloaded.
    """
    if not documents:
        return []

    with tracing.observe_step("retrieval.rerank", as_type="reranker",
                              input=tracing.io({"query": query, "candidates": len(documents), "top_k": top_k})) as obs:
        scores = None
        try:
            scores = _cross_encoder_scores(query, documents)
        except Exception as exc:  # model loaded but predict failed: fall back
            tracing.safe_update(obs, level="WARNING", status_message=f"cross-encoder failed: {exc}")
        if scores:
            indices = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)[:top_k]
            method = "cross_encoder"
        else:
            indices = _distance_based_rank(distances, top_k=top_k)
            method = "distance"

        def _label(i: int) -> str:
            m = (metadatas[i] if i < len(metadatas) else None) or {}
            return str(m.get("title") or m.get("dataset_id") or f"#{i}")[:120]

        ranking = [{"rank": r + 1, "index": i, "title": _label(i),
                    "distance": round(float(distances[i]), 4) if i < len(distances) else None,
                    "score": round(scores[i], 4) if scores else None}
                   for r, i in enumerate(indices)]
        otel.annotate_current_span(**{
            "rerank.method": method,
            "rerank.candidates": len(documents),
            "rerank.top_k": top_k,
            "gen_ai.request.model": OLLAMA_RERANKER_MODEL if scores else None,
        })
        tracing.safe_update(obs, output=ranking,
                            metadata={"method": method, "model": OLLAMA_RERANKER_MODEL if scores else None})
        tracing.fact(rerank_method=method)
        return indices
