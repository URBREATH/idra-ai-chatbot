import os
from typing import Any

from dotenv import load_dotenv

from app.common.utils.reranker_encoder import get_cross_encoder

load_dotenv()
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", 10))


def _distance_based_rank(distances: list[float], top_k: int = DEFAULT_TOP_K) -> list[int]:
    """Fallback ranking using ChromaDB cosine distances (lower distance = more similar)."""
    if not distances:
        return []
    ranked = sorted(range(len(distances)), key=lambda i: distances[i])
    return ranked[:top_k]


def _cross_encoder_rank(
    query: str,
    documents: list[str],
    top_k: int = DEFAULT_TOP_K,
) -> list[int]:
    """Rank documents using ms-marco-MiniLM-L-6-v2 cross-encoder (ADR-007)."""
    encoder = get_cross_encoder()
    if encoder is None or not documents:
        return []

    scores = encoder.predict([(query, doc) for doc in documents])
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

    indices = _cross_encoder_rank(query, documents, top_k=top_k)
    if indices:
        return indices

    return _distance_based_rank(distances, top_k=top_k)
