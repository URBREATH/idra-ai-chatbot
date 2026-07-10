from typing import Any

_CROSS_ENCODER = None
_CROSS_ENCODER_LOADED = False


def get_cross_encoder() -> Any | None:
    """Lazily load the ms-marco-MiniLM-L-6-v2 cross-encoder (ADR-007).

    Returns None when sentence_transformers is not installed or the model is
    unavailable, letting the reranker fall back to distance-based ordering.
    """
    global _CROSS_ENCODER, _CROSS_ENCODER_LOADED
    if _CROSS_ENCODER_LOADED:
        return _CROSS_ENCODER

    _CROSS_ENCODER_LOADED = True
    try:
        from sentence_transformers import CrossEncoder  # type: ignore

        _CROSS_ENCODER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception:
        _CROSS_ENCODER = None
    return _CROSS_ENCODER
