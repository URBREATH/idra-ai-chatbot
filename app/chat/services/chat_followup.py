"""
followup.py — Makes the chatbot interactive by rewriting follow-up questions into
standalone search queries, using the conversation history.

Handles two kinds of follow-up:
  1. Refinements that reference the previous turn ("of those, only the CSV ones").
  2. Reactions/constraints that reject a suggestion and ask for an alternative
     ("I can't plant trees in my area" after a tree-planting NBS was proposed).

Key idea for case 2: semantic search CANNOT exclude a concept — a query like
"solutions without trees" still pulls tree solutions, because it names 'trees'.
So the rewrite produces a POSITIVE query about the underlying PROBLEM (e.g. "urban
heat nature-based solutions"), and the user's constraint ("no trees") is honored
later, at generation time, where the model sees the original message and the
conversation. The retrieval brings the full pool of relevant solutions; the model
drops the rejected one and proposes alternatives.
"""

from __future__ import annotations
import logging
from app.ollama import client as ollama_client   # adapt to your real path
from app.config.config import _REFERENCE_MARKERS, _REACTION_MARKERS, _REWRITE_PROMPT

logger = logging.getLogger(__name__)

def is_followup(message: str) -> bool:
    """True if the message refers to, or reacts to, the previous turn."""
    m = " " + str(message or "").lower() + " "
    return any(w in m for w in _REFERENCE_MARKERS) or any(w in m for w in _REACTION_MARKERS)


def _clean(text: str) -> str:
    """Strip quotes/labels the model may add around the rewritten query."""
    t = str(text or "").strip().strip('"').strip("'").strip()
    if ":" in t and len(t.split(":", 1)[0]) < 30:
        after = t.split(":", 1)[1].strip()
        if after:
            t = after
    return t.strip()

async def rewrite_query(message: str, conversation_context: str,
                        model: str | None = None) -> str:
    """Rewrite a follow-up into a standalone, positive search query.
    On any failure returns the original message, so search still works."""
    if not conversation_context:
        return message
    prompt = _REWRITE_PROMPT.format(context=conversation_context, message=message)
    try:
        if model:
            raw = await ollama_client.generate_completion(prompt, model=model, temperature=0.0)
        else:
            raw = await ollama_client.generate_completion(prompt, temperature=0.0)
    except Exception as e:
        logger.debug("Query rewrite failed, using original message: %s", e)
        return message
    rewritten = _clean(raw)
    if not rewritten or len(rewritten) > 300:
        return message
    logger.debug("FOLLOW-UP rewrite: %r -> %r", message, rewritten)
    return rewritten